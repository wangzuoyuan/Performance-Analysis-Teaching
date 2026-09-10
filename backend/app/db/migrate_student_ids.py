"""跨届撞号迁移：高二重新编号后，新学号可能撞历史旧学号。

学校的学号在分班/升级后重新编号时，新编号值域可能覆盖旧编号（如高一
7250629=刘梓烨，高二重新编号后 7250629=孙仲仁）。student_id 字符串被假设
全局唯一（student_alias 有唯一约束），撞号会破坏这一前提：

- 画像按学号串数据 → 孙仲仁继承到刘梓烨的高一成绩；
- 姓名取自成绩表 → 画像页显示成别人。

迁移策略：高二新号是「活号」（今后上传/作业都用它），历史旧号是「死号」
（存量不再新增）。把死号行的学号改写为带届别命名空间的 ID（g<年级>-<原号>，
如 g1-7250629），恢复字符串唯一性；随后按姓名把死号与同名成员的当前学号
自动建「身份链」，画像经链正确合并跨学年历史。

幂等：改写后同学号只剩一个姓名，不再命中检测；已建链跳过。显示层用
strip_id_namespace 把 g 前缀还原为原学号。
"""

import re

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.analysis.scope import strip_id_namespace

# g1-7250629 / g2-2301001 等；识别「命名空间化学号」
_NS_PATTERN = re.compile(r"^g(\d+)-(.+)$")


def _namespaced_sid(grade, sid: str) -> str:
    return f"g{int(grade) if grade is not None else 0}-{sid}"


def migrate_colliding_student_ids(db: Session) -> dict:
    """检测并修复「同一学号对应多个姓名」的撞号。可重复执行。

    返回 {collisions, rekeyed_rows, rekeyed_ids, linked, pending}：
    - collisions 命中撞号的学号数
    - rekeyed_rows/rekeyed_ids 改写行数/学号数
    - linked 自动建链对数；pending 未能自动建链的 {new_sid, name, reason}
    """
    from app.db.models import (
        ClassRoster,
        Exam,
        StudentAlias,
        StudentIdentity,
        SubjectScore,
        TeachingClassMember,
        TotalScore,
    )

    stats = {"collisions": 0, "rekeyed_rows": 0, "rekeyed_ids": 0, "linked": 0, "pending": []}

    grade_map = {
        row[0]: row[1]
        for row in db.query(Exam.id, Exam.grade).all()
    }

    # 批量预载「学号 → 姓名集合」映射，内存中筛选候选，快路径仅 3 次扫描
    score_names: dict[str, set[str]] = {}
    for sid, nm in db.query(SubjectScore.student_id, SubjectScore.name).all():
        nm = (nm or "").strip()
        if nm:
            score_names.setdefault(sid, set()).add(nm)
    roster_map: dict[str, set[str]] = {}
    for sid, nm in db.query(ClassRoster.student_id, ClassRoster.name).all():
        nm = (nm or "").strip()
        if nm:
            roster_map.setdefault(sid, set()).add(nm)
    member_map: dict[str, set[str]] = {}
    for sid, nm in db.query(TeachingClassMember.student_id, TeachingClassMember.name).all():
        nm = (nm or "").strip()
        if nm:
            member_map.setdefault(sid, set()).add(nm)

    # 花名册残留姓名修正：补录学号合并旧花名册行时曾保留旧生姓名。
    # 成员表是老师录入的当前身份，学号有成员行时花名册姓名以成员为准。
    for sid, mnames in member_map.items():
        rnames = roster_map.get(sid)
        if rnames and not (rnames & mnames):
            row = db.get(ClassRoster, sid)
            if row:
                row.name = sorted(mnames)[0]
                roster_map[sid] = {row.name}

    # 候选：教师侧（成员/花名册）持有该学号，且成绩里存在与教师侧姓名
    # 不一致的行。纯历史学号（教师侧无人持有）无当前身份争议，不动。
    # 成员姓名优先（老师录入的当前身份），花名册可能残留上一届旧生姓名，
    # 仅在无成员行时兜底。
    candidates = []
    for sid, names in score_names.items():
        active = member_map.get(sid, set()) or roster_map.get(sid, set())
        if active and (names - active):
            candidates.append(sid)

    for sid in candidates:
        stats["collisions"] += 1
        rows = (
            db.query(SubjectScore)
            .filter(SubjectScore.student_id == sid)
            .all()
        )
        # 按姓名分组：{姓名: [行...]}；姓名为空的行无法判定归属，不动
        groups: dict[str, list] = {}
        for r in rows:
            key = (r.name or "").strip()
            if key:
                groups.setdefault(key, []).append(r)
        if not groups:
            continue

        active_names = member_map.get(sid, set()) or roster_map.get(sid, set())
        # 未命中教师侧姓名的组都是「别人的历史」，改写为命名空间学号；
        # 若教师侧姓名在成绩中尚无行（高二成绩未导入的常见时序），全部组改写
        dead = [
            (name, grp) for name, grp in groups.items()
            if name not in active_names
        ]

        for dead_name, dead_rows in dead:
            grades = [grade_map.get(r.exam_id) for r in dead_rows]
            grades = [g for g in grades if g is not None]
            new_sid = _namespaced_sid(min(grades) if grades else None, sid)
            if new_sid == sid:
                continue
            existing = (
                db.query(SubjectScore.id)
                .filter(SubjectScore.student_id == new_sid)
                .first()
            )
            if existing:
                # 目标命名空间学号已存在（异常残留），跳过待人工处理
                stats["pending"].append(
                    {"new_sid": new_sid, "name": dead_name, "reason": "target_sid_exists"}
                )
                continue

            exam_ids = {r.exam_id for r in dead_rows}
            for r in dead_rows:
                r.student_id = new_sid
            stats["rekeyed_rows"] += len(dead_rows)
            stats["rekeyed_ids"] += 1
            # 旧库遗留的总分行按同批考试改指，保持与成绩行一致
            stats["rekeyed_rows"] += (
                db.query(TotalScore)
                .filter(
                    TotalScore.student_id == sid,
                    TotalScore.exam_id.in_(exam_ids),
                )
                .update(
                    {TotalScore.student_id: new_sid},
                    synchronize_session=False,
                )
            )

            # 按姓名自动建链：死号（g1-7250629=刘梓烨）↔ 当前成员里唯一的同名学号
            candidates = {
                row[0]
                for row in db.query(TeachingClassMember.student_id)
                .filter(
                    func.trim(TeachingClassMember.name) == dead_name,
                    TeachingClassMember.student_id != sid,
                    TeachingClassMember.student_id != new_sid,
                )
                .all()
            }
            candidates = {
                c for c in candidates
                if not (c or "").startswith("_anon") and not _NS_PATTERN.match(c)
            }
            if len(candidates) != 1:
                stats["pending"].append(
                    {
                        "new_sid": new_sid,
                        "name": dead_name,
                        "reason": "ambiguous" if len(candidates) > 1 else "no_candidate",
                    }
                )
                continue
            target_sid = candidates.pop()
            existing_alias = (
                db.query(StudentAlias)
                .filter(StudentAlias.student_id == new_sid)
                .first()
            )
            if existing_alias:
                continue
            target_alias = (
                db.query(StudentAlias)
                .filter(StudentAlias.student_id == target_sid)
                .first()
            )
            if target_alias:
                identity_id = target_alias.identity_id
            else:
                identity = StudentIdentity(display_name=dead_name)
                db.add(identity)
                db.flush()
                identity_id = identity.id
                db.add(StudentAlias(
                    identity_id=identity_id,
                    student_id=target_sid,
                    link_source="collision_auto",
                ))
            db.add(StudentAlias(
                identity_id=identity_id,
                student_id=new_sid,
                grade=min(grades) if grades else None,
                link_source="collision_auto",
            ))
            stats["linked"] += 1

    db.commit()
    return stats
