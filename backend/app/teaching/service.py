"""教学班配置与成员维护的业务逻辑（被 router 与上传钩子共用）。

成员关系四条来源（对应 D1 / 06）：
- class_num：高一行政班，成员 = 该年级 class_num==int(label) 的学号；
- parser：上传带教学班列的成绩表，按 class_label 自动加成员；
- manual / roster：老师粘贴学号/姓名清单或上传花名册 Excel（姓名→学号反查）。

姓名→学号反查（绝不自动按姓名链接身份）：唯一命中直接落；多名候选返回待人工
消歧（附行政班/最近名次）；零命中进未匹配列表。
"""
from __future__ import annotations

import re
from typing import Optional


# 仅姓名录入（学号未知）的占位学号前缀。真实学号均为纯数字，永不会以本前缀开头，
# 故 analysis 端按 student_id 过滤时这些占位成员天然被排除（成绩表里没有匹配行）。
ANON_PREFIX = "_anon:"


class ConflictError(Exception):
    """成员学号重指时与另一名学生冲突（如同班两条不同姓名指向同一学号）。"""


def is_anon_sid(sid: Optional[str]) -> bool:
    return bool(sid) and sid.startswith(ANON_PREFIX)


def anon_sid_for(name: str, teaching_class_id) -> str:
    """某教学班内「仅姓名」学生的占位学号：`_anon:<教学班id>:<姓名>`。

    带上教学班 id 是为了让不同班的同名仅姓名学生互不共用学号——否则两个班里
    的同名（且是不同人）会指向同一占位学号，缺交/记录会跨班串到一起。"""
    return f"{ANON_PREFIX}{int(teaching_class_id)}:{(name or '').strip()}"


def is_class_scoped_anon(sid: Optional[str]) -> bool:
    """占位学号是否已是「按教学班隔离」的新格式 `_anon:<数字>:...`。"""
    if not is_anon_sid(sid):
        return False
    return bool(re.match(r"^\d+:", sid[len(ANON_PREFIX):]))


def name_from_anon_sid(sid: Optional[str]) -> str:
    """从占位学号取回姓名，兼容旧格式 `_anon:<姓名>` 与新格式 `_anon:<id>:<姓名>`。"""
    if not is_anon_sid(sid):
        return ""
    rest = sid[len(ANON_PREFIX):]
    m = re.match(r"^\d+:(.*)$", rest)
    return m.group(1) if m else rest


def ensure_anon_roster(db, tc, anon_sid: str, name: str) -> None:
    """给新建的「仅姓名」占位成员补一条花名册行（作业模块的学生主体）。

    花名册是缺交/特殊记录的外键目标；仅姓名成员若不进花名册，作业看板会显示
    「0 名有效学生」、录入缺交时也匹配不到。已存在则跳过（幂等）。"""
    from app.db.models import ClassRoster

    if db.query(ClassRoster.student_id).filter(ClassRoster.student_id == anon_sid).first():
        return
    db.add(ClassRoster(student_id=anon_sid, name=name, class_label=tc.label))


def name_to_student_ids(db, name: str, grade: Optional[int] = None) -> list[str]:
    """按姓名反查学号（来源 SubjectScore.name，可选 ClassRoster.name）。返回去重学号列表。"""
    from app.db.models import ClassRoster, Exam, SubjectScore
    from sqlalchemy import distinct

    ids: list[str] = []
    q = db.query(distinct(SubjectScore.student_id)).filter(SubjectScore.name == name)
    if grade is not None:
        q = q.join(Exam, Exam.id == SubjectScore.exam_id).filter(Exam.grade == grade)
    ids.extend(r[0] for r in q.all())
    # 花名册补充（作业模块可能已有该生但尚无成绩）；跳过「仅姓名」占位学号，
    # 它们只是某教学班内的姓名占位，不是全局的人标识，不能作为反查命中。
    rq = db.query(ClassRoster.student_id).filter(ClassRoster.name == name)
    for r in rq.all():
        if r[0] not in ids and not is_anon_sid(r[0]):
            ids.append(r[0])
    return ids


def student_exists(db, student_id: str) -> bool:
    """该学号是否在成绩库或花名册中出现过。"""
    from app.db.models import ClassRoster, SubjectScore

    if db.query(SubjectScore.id).filter(SubjectScore.student_id == student_id).first():
        return True
    if db.query(ClassRoster.student_id).filter(ClassRoster.student_id == student_id).first():
        return True
    return False


def student_name(db, student_id: str) -> Optional[str]:
    from app.db.models import ClassRoster, SubjectScore

    row = (
        db.query(SubjectScore.name)
        .filter(SubjectScore.student_id == student_id, SubjectScore.name.isnot(None))
        .first()
    )
    if row and row[0]:
        return row[0]
    r = db.query(ClassRoster.name).filter(ClassRoster.student_id == student_id).first()
    return r[0] if r else None


def classify_member(db, tc_grade: int, student_id: str) -> str:
    """判定成员状态：inherited（已继承跨学段学情）/ new（新学生）。
    inherited = 该学号经身份层解析出的同一人，存在比当前年级更低的学号记录。"""
    from app.analysis.scope import student_ids_of_person, identity_of
    from app.db.models import Exam, SubjectScore

    if identity_of(db, student_id) is None:
        return "new"
    ids = student_ids_of_person(db, student_id)
    # 这些学号里有没有出现在更低年级的成绩
    other = {sid for sid in ids if sid != student_id}
    if not other:
        return "new"
    lower = (
        db.query(Exam.grade)
        .join(SubjectScore, SubjectScore.exam_id == Exam.id)
        .filter(SubjectScore.student_id.in_(other), Exam.grade < tc_grade)
        .distinct()
        .all()
    )
    return "inherited" if lower else "new"


def _looks_like_student_id(token: str) -> bool:
    t = token.strip()
    return t.isdigit() and len(t) >= 5


_LINE_FIELD = re.compile(r"[\s,，;；、\t]+")


def parse_entries(lines: list[str] | None = None, tokens: list[str] | None = None) -> list[dict]:
    """把粘贴文本行 / 学号清单解析成统一条目。

    每项为
      {"student_id": sid, "name": name} —— 行内「学号 姓名」成对识别；
      {"raw": token}                      —— 单 token，交判别逻辑（学号 / 姓名）。

    行首段为学号（≥5 位数字）、且第二段不是学号时，整行视为「学号 姓名」；
    否则按分隔符拆成多个单 token（兼容「7100001,7100002」「张三,李四」一行多项）。"""
    entries: list[dict] = []
    for line in lines or []:
        line = (line or "").strip()
        if not line:
            continue
        parts = [p for p in _LINE_FIELD.split(line) if p]
        if (
            len(parts) >= 2
            and _looks_like_student_id(parts[0])
            and not _looks_like_student_id(parts[1])
        ):
            sid = parts[0].strip()
            name = "".join(p.strip() for p in parts[1:]).strip()
            entries.append({"student_id": sid, "name": name or None})
        else:
            for p in parts:
                entries.append({"raw": p})
    for tok in tokens or []:
        tok = (tok or "").strip()
        if tok:
            entries.append({"raw": tok})
    return entries


def _member_index(db, tc):
    """返回本班成员 (rows, existing_sids, by_name)。by_name: 姓名 → [student_id]。"""
    from app.db.models import TeachingClassMember

    rows = (
        db.query(TeachingClassMember)
        .filter(TeachingClassMember.teaching_class_id == tc.id)
        .all()
    )
    existing = {r.student_id for r in rows}
    by_name: dict[str, list[str]] = {}
    for r in rows:
        nm = (r.name or "").strip()
        if nm:
            by_name.setdefault(nm, []).append(r.student_id)
    return rows, existing, by_name


def _reindex(existing: set, by_name: dict, *, removed_sid: str, added_sid: str, added_name) -> None:
    """reassign 后同步内存索引。"""
    existing.discard(removed_sid)
    existing.add(added_sid)
    for nm, lst in list(by_name.items()):
        if removed_sid in lst:
            filtered = [s for s in lst if s != removed_sid]
            if filtered:
                by_name[nm] = filtered
            else:
                del by_name[nm]
    if added_name:
        by_name.setdefault(added_name, []).append(added_sid)


def _place_id(db, tc, sid: str, name, upsert: bool, existing: set, by_name: dict):
    """处理一条「带学号」的条目，返回 (action, info)。

    action ∈ added / exists / upgraded / reassigned / ambiguous：
    - exists：已是成员（必要时补姓名缓存）；
    - reassigned：覆盖模式下按姓名命中本班成员并改指；
    - upgraded：把同名「仅姓名」占位成员升级为真实学号；
    - added：新增；ambiguous：覆盖模式下同名多人，无法确定覆盖谁。"""
    from app.db.models import TeachingClassMember

    sid = sid.strip()
    if sid in existing:
        if name:
            row = (
                db.query(TeachingClassMember)
                .filter(
                    TeachingClassMember.teaching_class_id == tc.id,
                    TeachingClassMember.student_id == sid,
                )
                .first()
            )
            if row and not row.name:
                row.name = name
                by_name.setdefault(name, []).append(sid)
        return "exists", {"student_id": sid, "name": name}

    if upsert and name and name in by_name:
        matches = by_name.get(name, [])
        if len(matches) == 1:
            old = matches[0]
            reassign_member_id(db, tc, old, sid, name=name)
            _reindex(existing, by_name, removed_sid=old, added_sid=sid, added_name=name)
            return "reassigned", {"student_id": sid, "name": name, "old": old}
        return "ambiguous", {"name": name, "student_id": sid}

    # 自动升级：存在同名的「仅姓名」占位成员 → 升级为真实学号（避免重复占位）
    if name:
        anon = anon_sid_for(name, tc.id)
        if anon in existing:
            reassign_member_id(db, tc, anon, sid, name=name)
            _reindex(existing, by_name, removed_sid=anon, added_sid=sid, added_name=name)
            return "upgraded", {"student_id": sid, "name": name, "old": anon}

    db.add(
        TeachingClassMember(
            teaching_class_id=tc.id, student_id=sid, name=name, source="manual"
        )
    )
    existing.add(sid)
    if name:
        by_name.setdefault(name, []).append(sid)
    return "added", {"student_id": sid, "name": name}


def _ambiguous_entry(db, tc_grade: int, name: str) -> dict:
    """构造同名消歧条目：候选含学号 / 行政班 / 最近任教学科成绩（不再用主三门名次）。

    单学科化（阶段7）：不再查询 TotalScore。改用教师唯一任教学科的最近一次
    合法成绩（raw_score / grade_score）辅助辨认同名。
    """
    from app.db.models import Exam, SubjectScore, Teacher

    teacher_subj = None
    teacher = db.query(Teacher).first()
    if teacher:
        teacher_subj = teacher.subject

    cands = []
    for sid in name_to_student_ids(db, name):
        nm = student_name(db, sid) or name
        cls = (
            db.query(SubjectScore.class_num)
            .filter(SubjectScore.student_id == sid, SubjectScore.class_num.isnot(None))
            .first()
        )
        latest_score = None
        if teacher_subj:
            latest = (
                db.query(SubjectScore.raw_score, SubjectScore.grade_score)
                .join(Exam, Exam.id == SubjectScore.exam_id)
                .filter(
                    SubjectScore.student_id == sid,
                    SubjectScore.subject == teacher_subj,
                )
                .order_by(Exam.exam_date.desc(), SubjectScore.id.desc())
                .first()
            )
            if latest:
                latest_score = latest[0] if latest[0] is not None else latest[1]
        cands.append(
            {
                "student_id": sid,
                "name": nm,
                "class_num": cls[0] if cls else None,
                "latest_rank": None,  # 保留字段名兼容前端；不再来自主三门名次
                "latest_score": latest_score,
            }
        )
    return {"name": name, "candidates": cands}


def resolve_import(
    db,
    tc,
    lines: list[str] | None = None,
    tokens: list[str] | None = None,
    upsert: bool = False,
) -> dict:
    """批量解析并导入成员清单。

    - 行内「学号 姓名」→ 学号 + 姓名成员；
    - 单学号 → 学号成员（姓名反查补）；
    - 单姓名唯一命中 → 该学号成员；
    - 单姓名多名命中 → ambiguous（候选）；
    - 单姓名零命中 → 新增「仅姓名」占位成员（_anon:姓名），可日后改学号。

    upsert=True 时，「学号 姓名」行按姓名匹配本班已有成员并覆盖其学号（学号变更
    后整表重导用）。绝不按姓名自动建身份链接。"""
    from app.db.models import TeachingClassMember

    entries = parse_entries(lines, tokens)
    _, existing, by_name = _member_index(db, tc)

    # 预扫：本次导入内「同名 → 多个不同学号」属手误冲突，整组判歧义、都不落
    pair_ids_by_name: dict[str, set[str]] = {}
    for e in entries:
        if e.get("student_id") and e.get("name"):
            pair_ids_by_name.setdefault(e["name"], set()).add(e["student_id"])
    intra_conflict: dict[str, set[str]] = {
        n: ids for n, ids in pair_ids_by_name.items() if len(ids) > 1
    }

    matched: list[dict] = []
    name_only: list[dict] = []
    ambiguous: list[dict] = [
        {
            "name": name,
            "candidates": [
                {"student_id": cid, "name": name, "class_num": None, "latest_rank": None}
                for cid in sorted(ids)
            ],
        }
        for name, ids in intra_conflict.items()
    ]
    unmatched: list[dict] = []
    added = 0
    reassigned = 0

    def _record_matched(sid, name):
        return {"student_id": sid, "name": name, "state": classify_member(db, tc.grade, sid)}

    for e in entries:
        sid = e.get("student_id")
        if sid:
            name = e.get("name") or student_name(db, sid) or None
            if name and name in intra_conflict:
                continue
            action, _ = _place_id(db, tc, sid, name, upsert, existing, by_name)
            if action == "added":
                added += 1
            elif action == "reassigned":
                reassigned += 1
            elif action == "ambiguous":
                ambiguous.append(_ambiguous_entry(db, tc.grade, name))
                continue
            matched.append(_record_matched(sid, name))
            continue

        tok = (e.get("raw") or "").strip()
        if not tok:
            continue
        if _looks_like_student_id(tok):
            name = student_name(db, tok) or None
            action, _ = _place_id(db, tc, tok, name, upsert, existing, by_name)
            if action == "added":
                added += 1
            elif action == "reassigned":
                reassigned += 1
            matched.append(_record_matched(tok, name))
            continue

        ids = name_to_student_ids(db, tok)
        if len(ids) == 1:
            sid0 = ids[0]
            action, _ = _place_id(db, tc, sid0, tok, upsert, existing, by_name)
            if action == "added":
                added += 1
            elif action == "reassigned":
                reassigned += 1
            matched.append(_record_matched(sid0, tok))
        elif len(ids) > 1:
            ambiguous.append(_ambiguous_entry(db, tc.grade, tok))
        else:
            # 零命中：落「仅姓名」占位成员，可日后补学号
            anon = anon_sid_for(tok, tc.id)
            # 本班已有同名成员（含已设学号的）→ 不重复落占位，避免重复
            if tok in by_name:
                name_only.append({"student_id": by_name[tok][0], "name": tok, "state": "exists"})
                continue
            if anon in existing:
                name_only.append({"student_id": anon, "name": tok, "state": "exists"})
                continue
            db.add(
                TeachingClassMember(
                    teaching_class_id=tc.id, student_id=anon, name=tok, source="manual"
                )
            )
            ensure_anon_roster(db, tc, anon, tok)
            existing.add(anon)
            by_name.setdefault(tok, []).append(anon)
            added += 1
            name_only.append({"student_id": anon, "name": tok, "state": "name_only"})

    db.commit()
    return {
        "matched": matched,
        "name_only": name_only,
        "ambiguous": ambiguous,
        "unmatched": unmatched,
        "added_count": added,
        "reassigned_count": reassigned,
    }


def add_by_names_and_ids(
    db, tc, student_ids: list[str] | None = None, names: list[str] | None = None
) -> dict:
    """单条添加成员（添加成员 tab）：student_ids 按字面学号直接落（不限位数）；
    names 走反查（唯一命中落、同名返回 candidate_ids、零命中落「仅姓名」占位）。
    返回 {added, ambiguous:[{name,candidate_ids}], name_only}。"""
    from app.db.models import TeachingClassMember

    _, existing, by_name = _member_index(db, tc)
    added = 0
    name_only: list[dict] = []
    ambiguous: list[dict] = []

    for sid in student_ids or []:
        sid = (sid or "").strip()
        if not sid:
            continue
        # 尽量反查姓名，以便把同名「仅姓名」占位成员升级为该学号（避免重复）。
        # 该学号尚无任何成绩/花名册记录时反查为空，无法去重——属预期，可用「学号 姓名」导入或日后 PATCH 补。
        resolved = student_name(db, sid)
        action, _ = _place_id(db, tc, sid, resolved, False, existing, by_name)
        if action == "added":
            added += 1

    for name in names or []:
        name = (name or "").strip()
        if not name:
            continue
        ids = name_to_student_ids(db, name)
        if len(ids) == 1:
            action, _ = _place_id(db, tc, ids[0], name, False, existing, by_name)
            if action == "added":
                added += 1
        elif len(ids) > 1:
            ambiguous.append({"name": name, "candidate_ids": ids})
        else:
            anon = anon_sid_for(name, tc.id)
            # 本班已有同名成员 → 不重复落占位
            if name in by_name or anon in existing:
                continue
            db.add(
                TeachingClassMember(
                    teaching_class_id=tc.id, student_id=anon, name=name, source="manual"
                )
            )
            ensure_anon_roster(db, tc, anon, name)
            existing.add(anon)
            by_name.setdefault(name, []).append(anon)
            added += 1
            name_only.append({"student_id": anon, "name": name})

    db.commit()
    return {"added": added, "ambiguous": ambiguous, "name_only": name_only}


def reassign_member_id(db, tc, old_sid: str, new_sid: str, name: str | None = None) -> dict:
    """把成员学号从 old_sid 改为 new_sid（「学号换了」/ 给仅姓名成员补学号）。

    学号是「人」的全局标识，故连带迁移该人的教师侧数据：成员关系（跨所有班）、
    花名册、缺交 / 特殊记录、成长档案、身份别名。**成绩表（subject_score /
    total_score / class_average）不动**——成绩来自上传的不可变源，跨学年学号变更
    应走「身份链接」。返回 {old, new, name, cascaded}。"""
    from app.db.models import (
        ClassRoster,
        HomeworkRecord,
        SpecialRecord,
        StudentAlias,
        StudentNote,
        TeachingClassMember,
    )

    new_sid = (new_sid or "").strip()
    if not new_sid:
        raise ValueError("新学号不能为空")
    if is_anon_sid(new_sid):
        raise ValueError("新学号须为真实学号，不能仍为仅姓名占位")
    old_sid = old_sid or ""
    name = (name or "").strip() or None

    target = (
        db.query(TeachingClassMember)
        .filter(
            TeachingClassMember.teaching_class_id == tc.id,
            TeachingClassMember.student_id == old_sid,
        )
        .first()
    )
    if not target:
        raise ValueError("成员不存在")

    cascaded = {"members": 0, "roster": 0, "homework": 0, "special": 0, "notes": 0, "alias": 0}

    if old_sid == new_sid:
        if name:
            target.name = name
        db.commit()
        return {"old": old_sid, "new": new_sid, "name": name, "cascaded": cascaded}

    old_is_anon = is_anon_sid(old_sid)

    # 本班冲突：新学号已是本班另一成员 → 一律拒绝。无法可靠判定「同人」，
    # 静默合并会把两个不同学生的档案/缺交并到一起（不可逆）。真有重复请先删一条。
    conflict = (
        db.query(TeachingClassMember)
        .filter(
            TeachingClassMember.teaching_class_id == tc.id,
            TeachingClassMember.student_id == new_sid,
        )
        .first()
    )
    if conflict and conflict.id != target.id:
        who = conflict.name or conflict.student_id
        raise ConflictError(f"学号 {new_sid} 已是本班成员「{who}」，不能重复绑定")

    target.student_id = new_sid
    if name:
        target.name = name
    elif not target.name:
        target.name = student_name(db, new_sid)

    # 仅姓名占位（_anon:姓名）只在「本班·本姓名」范围内有效，不是全局人标识：
    # 同名不同人会在多班各占一行，绝不能跨班/别名联动。但占位成员现在也进花名册、
    # 也可能已录了缺交，需要把这些「本人数据」迁到真实学号——除非该占位学号仍被
    # 其它班成员共用（同名多人），那样迁移会误伤他人，改为给新学号补一张空花名册。
    anon_shared = old_is_anon and (
        db.query(TeachingClassMember)
        .filter(
            TeachingClassMember.student_id == old_sid,
            TeachingClassMember.id != target.id,
        )
        .first()
        is not None
    )
    migrate_person_data = (not old_is_anon) or (not anon_shared)

    if not old_is_anon:
        # 其它班同一（真实）学号的成员行：一并改（新学号已在那个班则合并删除）
        other_rows = (
            db.query(TeachingClassMember)
            .filter(
                TeachingClassMember.teaching_class_id != tc.id,
                TeachingClassMember.student_id == old_sid,
            )
            .all()
        )
        for row in other_rows:
            cc = (
                db.query(TeachingClassMember)
                .filter(
                    TeachingClassMember.teaching_class_id == row.teaching_class_id,
                    TeachingClassMember.student_id == new_sid,
                )
                .first()
            )
            if cc:
                db.delete(row)
            else:
                row.student_id = new_sid
            cascaded["members"] += 1

    if migrate_person_data:
        # 花名册（PK=student_id，避免主键冲突：新学号已有花名册则删旧留新）
        old_roster = db.query(ClassRoster).filter(ClassRoster.student_id == old_sid).first()
        if old_roster:
            if db.query(ClassRoster).filter(ClassRoster.student_id == new_sid).first():
                db.delete(old_roster)
            else:
                old_roster.student_id = new_sid
            cascaded["roster"] += 1

        # 缺交 / 特殊 / 档案：无学号唯一约束，直接批量改指
        cascaded["homework"] = (
            db.query(HomeworkRecord)
            .filter(HomeworkRecord.student_id == old_sid)
            .update({HomeworkRecord.student_id: new_sid}, synchronize_session=False)
        )
        cascaded["special"] = (
            db.query(SpecialRecord)
            .filter(SpecialRecord.student_id == old_sid)
            .update({SpecialRecord.student_id: new_sid}, synchronize_session=False)
        )
        cascaded["notes"] = (
            db.query(StudentNote)
            .filter(StudentNote.student_id == old_sid)
            .update({StudentNote.student_id: new_sid}, synchronize_session=False)
        )

    if not old_is_anon:
        # 身份别名（student_id 唯一）：新学号已有别名 → 视作两人，不自动合并，跳过
        old_alias = db.query(StudentAlias).filter(StudentAlias.student_id == old_sid).first()
        if old_alias and not db.query(StudentAlias).filter(StudentAlias.student_id == new_sid).first():
            old_alias.student_id = new_sid
            cascaded["alias"] += 1

    # 占位学号被同名多人共用而未迁移花名册时，给新学号补一张花名册，保证可继续跟踪
    if old_is_anon and not migrate_person_data:
        if not db.query(ClassRoster).filter(ClassRoster.student_id == new_sid).first():
            db.add(ClassRoster(student_id=new_sid, name=target.name, class_label=tc.label))
            cascaded["roster"] += 1

    db.commit()
    return {"old": old_sid, "new": new_sid, "name": name, "cascaded": cascaded}


def sync_by_class_num(db, tc) -> int:
    """高一/行政班：按 int(label) 从成绩库重算成员（仅覆盖 source=class_num 行，
    保留 manual/roster/parser）。返回成员总数。

    单学科化（阶段7）：不再内部 commit——由调用方（sync_members_after_upload /
    parse_and_store）统一控制事务边界，保证上传的原子性。
    """
    from app.db.models import Exam, SubjectScore, TeachingClassMember

    if tc.kind != "行政":
        return db.query(TeachingClassMember).filter(
            TeachingClassMember.teaching_class_id == tc.id
        ).count()
    try:
        cn = int(tc.label)
    except (TypeError, ValueError):
        return db.query(TeachingClassMember).filter(
            TeachingClassMember.teaching_class_id == tc.id
        ).count()

    ids = {
        r[0]
        for r in (
            db.query(SubjectScore.student_id)
            .join(Exam, Exam.id == SubjectScore.exam_id)
            .filter(Exam.grade == tc.grade, SubjectScore.class_num == cn)
            .distinct()
            .all()
        )
    }
    db.query(TeachingClassMember).filter(
        TeachingClassMember.teaching_class_id == tc.id,
        TeachingClassMember.source == "class_num",
    ).delete(synchronize_session=False)
    for sid in ids:
        db.add(
            TeachingClassMember(
                teaching_class_id=tc.id, student_id=sid, source="class_num"
            )
        )
    return db.query(TeachingClassMember).filter(
        TeachingClassMember.teaching_class_id == tc.id
    ).count()


def sync_members_after_upload(db, exam) -> None:
    """上传新考试后：对 kind=行政 班按 class_num 重算成员；对成绩带 class_label
    的，把对应学号补为 source=parser 成员（不覆盖已有 manual/roster）。

    单学科化（阶段7）：只维护当前教师任教学科的 TeachingClass。行政班（无 subject）
    仍按 class_num 同步；教学班只在 tc.subject == 教师任教学科 时维护，他科教学班
    不被扫描。不再内部 commit——由调用方（parse_and_store）统一控制事务边界。
    """
    from app.db.models import SubjectScore, Teacher, TeachingClass, TeachingClassMember

    teacher_subj = None
    teacher = db.query(Teacher).first()
    if teacher:
        teacher_subj = teacher.subject

    classes = (
        db.query(TeachingClass).filter(TeachingClass.grade == exam.grade).all()
    )
    for tc in classes:
        # §7：教学班只维护当前教师 subject 的班；行政班（无 subject）不受影响。
        if tc.kind == "教学" and teacher_subj and tc.subject != teacher_subj:
            continue
        if tc.kind == "行政":
            sync_by_class_num(db, tc)
        # parser 来源：本考试里 class_label 命中本班标签的学号自动加入
        existing = {
            r[0]
            for r in db.query(TeachingClassMember.student_id)
            .filter(TeachingClassMember.teaching_class_id == tc.id)
            .all()
        }
        sids = {
            r[0]
            for r in (
                db.query(SubjectScore.student_id)
                .filter(
                    SubjectScore.exam_id == exam.id,
                    SubjectScore.class_label == tc.label,
                )
                .distinct()
                .all()
            )
        }
        for sid in sids:
            if sid not in existing:
                db.add(
                    TeachingClassMember(
                        teaching_class_id=tc.id, student_id=sid, source="parser"
                    )
                )
                existing.add(sid)


def candidate_classes(db, grade: int) -> dict:
    """扫出该年级可选的行政班号 + 教学班标签（建班向导预填用）。

    单学科化（阶段7）：只返回当前教师任教学科有真实分数（raw_score / grade_score
    至少一个非空）的班号/教学班标签。旧库含他科 SubjectScore 行不得进入设置页。
    """
    from app.db.models import Exam, SubjectScore, Teacher
    from sqlalchemy import distinct

    teacher_subj = None
    teacher = db.query(Teacher).first()
    if teacher:
        teacher_subj = teacher.subject

    subj_filter = []
    if teacher_subj:
        subj_filter.append(SubjectScore.subject == teacher_subj)
        subj_filter.append(
            (SubjectScore.raw_score.isnot(None)) | (SubjectScore.grade_score.isnot(None))
        )

    class_nums = sorted(
        {
            r[0]
            for r in (
                db.query(distinct(SubjectScore.class_num))
                .join(Exam, Exam.id == SubjectScore.exam_id)
                .filter(Exam.grade == grade, SubjectScore.class_num.isnot(None), *subj_filter)
                .all()
            )
        }
    )
    class_labels = sorted(
        {
            r[0]
            for r in (
                db.query(distinct(SubjectScore.class_label))
                .join(Exam, Exam.id == SubjectScore.exam_id)
                .filter(Exam.grade == grade, SubjectScore.class_label.isnot(None), *subj_filter)
                .all()
            )
        }
    )
    return {
        "grade": grade,
        "class_nums": class_nums,
        "class_labels": class_labels,
    }
