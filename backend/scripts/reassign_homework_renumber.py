#!/usr/bin/env python3
"""作业/特殊记录换届改号归位维护脚本（可复跑）。

背景：升年级/分班后学号「错位滚动」（旧号=上一届学生、新号=本届学生），而
homework_record / special_record 没有身份链概念，分班前的记录会挂在旧号下、
被新号主人张冠李戴；旧号无人持有时本人记录则彻底消失于统计。本脚本按分班
切割日期把切割点之前的记录归位：

- 已建链旧号（student_alias 中指向唯一当前成员）→ 改挂该成员的现学号
- 离校/未建链旧号（成绩表学号宇宙内、非当前成员）→ 改写为 ``g<年级>-旧号``
  命名空间（与 subject_score 撞号迁移同一约定），退出当前号池
- 切割点之后的记录：新号即本人，一律原样
- 切割点前、学号前后届同人同号（无 alias）的成员行不动

用法::

    python scripts/reassign_homework_renumber.py --db ~/.exam-tracker/db.sqlite --cutoff 2026-07-01 --dry-run
    python scripts/reassign_homework_renumber.py --db db.sqlite --cutoff 2026-07-01
    python scripts/reassign_homework_renumber.py --db db.sqlite --cutoff 2026-07-01 --backup 修复前快照.sqlite

幂等与安全：
- 默认模式把「当前库」当作原始库，适用于尚未修复的库；若库里已存在
  ``g<数字>-`` 命名空间的作业记录（修复签名），说明已归位过，直接拒跑——
  已归位库上按当前学号重推会把别人名下的记录再挪一次。此时改用 --backup
  指定修复前快照进入重建模式。
- --backup 重建模式按备份原始学号 + 切割日期逐行（按行 id）推导权威值覆写，
  幂等：重复运行为 no-op，中途出错重跑也收敛到同一结果。
- 运行前先自行备份数据库；--dry-run 只打印归位计划不写库。
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import Counter, defaultdict

G_PREFIX = re.compile(r"^g(\d+)-")
TABLES = ("homework_record", "special_record")


def _bare(sid: str) -> str:
    return G_PREFIX.sub("", sid)


class Context:
    def __init__(self, conn: sqlite3.Connection):
        c = conn.cursor()
        self.member_names: dict = {}
        for sid, name in c.execute("SELECT student_id, name FROM teaching_class_member"):
            if name and sid not in self.member_names:
                self.member_names[sid] = name.strip()
        self.member_ids = {
            r[0] for r in c.execute("SELECT DISTINCT student_id FROM teaching_class_member")
        }
        # 成绩表学号宇宙（剥命名空间前缀后的裸号）
        self.universe = set()
        for (sid,) in c.execute("SELECT DISTINCT student_id FROM subject_score"):
            self.universe.add(_bare(sid))
        # 身份链：alias 组内恰好一个当前成员时，其余学号（剥前缀）→ 该成员
        groups: dict = defaultdict(set)
        for sid, iid in c.execute("SELECT student_id, identity_id FROM student_alias"):
            groups[iid].add(sid)
        self.pairs: dict = {}
        for _iid, ids in groups.items():
            targets = ids & self.member_ids
            if len(targets) != 1:
                continue
            tgt = next(iter(targets))
            for old in ids:
                bare = _bare(old)
                if bare != tgt:
                    self.pairs[bare] = tgt
        self._ns_cache: dict = {}
        self._name_cache: dict = {}

    def score_name(self, conn: sqlite3.Connection, sid: str):
        """裸号（含其命名空间形式）在成绩表里的主要姓名，即高一号主人。"""
        if sid in self._name_cache:
            return self._name_cache[sid]
        rows = conn.execute(
            "SELECT name, COUNT(*) FROM subject_score "
            "WHERE (student_id = ? OR student_id LIKE 'g%-' || ?) AND name IS NOT NULL "
            "GROUP BY name ORDER BY 2 DESC LIMIT 1",
            (sid, sid),
        ).fetchone()
        name = (rows[0].strip() if rows else None) or None
        self._name_cache[sid] = name
        return name

    def ns_prefix(self, conn: sqlite3.Connection, sid: str) -> str:
        """命名空间前缀：优先复用成绩表已有 g<年级>- 形式，否则按成绩年级推。"""
        if sid in self._ns_cache:
            return self._ns_cache[sid]
        row = conn.execute(
            "SELECT student_id FROM subject_score WHERE student_id LIKE 'g%-' || ? LIMIT 1",
            (sid,),
        ).fetchone()
        prefix = None
        if row:
            m = G_PREFIX.match(row[0])
            if m:
                prefix = f"g{m.group(1)}-"
        if prefix is None:
            row = conn.execute(
                "SELECT e.grade FROM subject_score s JOIN exam e ON e.id = s.exam_id "
                "WHERE s.student_id = ? LIMIT 1",
                (sid,),
            ).fetchone()
            prefix = f"g{row[0]}-" if row and row[0] is not None else "g1-"
        self._ns_cache[sid] = prefix
        return prefix


def map_orig(ctx: Context, conn: sqlite3.Connection, sid: str, date: str, cutoff: str) -> str:
    """由原始学号 + 记录日期推导权威学号。"""
    if date >= cutoff:
        return sid  # 分班后：新号即本人
    if sid in ctx.pairs:
        return ctx.pairs[sid]
    if sid in ctx.member_ids and not G_PREFIX.match(sid):
        # 当前成员的号：若该裸号在成绩表里的高一主人姓名与成员不同，说明是
        # 被复用的旧号（错位滚动），切割点前的记录属于离校旧主 → 命名空间；
        # 姓名一致（含前后届同号同人）则是本人记录，原样保留。
        old_name = ctx.score_name(conn, sid)
        mine = ctx.member_names.get(sid)
        if sid in ctx.universe and old_name is not None and mine is not None and old_name != mine:
            return ctx.ns_prefix(conn, sid) + sid
        return sid
    if sid in ctx.member_ids:
        return sid
    if not G_PREFIX.match(sid) and _bare(sid) in ctx.universe:
        return ctx.ns_prefix(conn, sid) + sid  # 离校/未建链旧主 → 命名空间
    return sid


def reassign(
    db_path: str,
    cutoff: str,
    backup_path: str | None = None,
    dry_run: bool = False,
    out=sys.stdout,
) -> Counter:
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        marker = conn.execute(
            "SELECT COUNT(*) FROM homework_record WHERE student_id LIKE 'g%-%'"
        ).fetchone()[0]
        if backup_path:
            bak = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
            orig_src = bak
            mode = f"重建模式（原始值取自 {backup_path}）"
        else:
            if marker:
                raise SystemExit(
                    "拒跑：库中已存在 g<数字>- 命名空间的作业记录，说明已归位过；"
                    "在已归位库上按当前学号重推会二次串改。如需校验/修复，请用 "
                    "--backup 指定修复前快照进入重建模式。"
                )
            orig_src = conn
            mode = "首次归位模式（当前库即原始库）"
        ctx = Context(conn)
        changes: dict = defaultdict(list)  # (table, target) -> [row ids]
        report: Counter = Counter()  # (table, orig, target) -> n
        for table in TABLES:
            cur_map = dict(conn.execute(f"SELECT id, student_id FROM {table}").fetchall())
            for rid, orig, date in orig_src.execute(
                f"SELECT id, student_id, date FROM {table}"
            ):
                if rid not in cur_map:
                    continue  # 当前库已无此行（被删），跳过
                exp = map_orig(ctx, conn, orig, date, cutoff)
                if cur_map[rid] != exp:
                    changes[(table, exp)].append(rid)
                    report[(table, orig, exp)] += 1
        print(f"[{mode}] cutoff={cutoff} 待改写 {sum(report.values())} 行", file=out)
        for (table, orig, tgt), n in sorted(report.items()):
            print(f"  {table}: {orig} -> {tgt}: {n} 行", file=out)
        if dry_run:
            print("--dry-run：不写库", file=out)
            return report
        for (table, tgt), ids in sorted(changes.items()):
            ph = ",".join("?" * len(ids))
            conn.execute(
                f"UPDATE {table} SET student_id=? WHERE id IN ({ph})", [tgt] + ids
            )
        conn.commit()
        print(f"已提交 {sum(report.values())} 行改写", file=out)
        return report
    finally:
        conn.close()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--db", required=True, help="db.sqlite 路径")
    p.add_argument("--cutoff", required=True, help="分班切割日期 YYYY-MM-DD（该日及之后原样保留）")
    p.add_argument("--backup", help="修复前快照路径；给出则进入幂等重建模式")
    p.add_argument("--dry-run", action="store_true", help="只打印归位计划")
    args = p.parse_args(argv)
    reassign(args.db, args.cutoff, backup_path=args.backup, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
