"""维护脚本 scripts/reassign_homework_renumber.py 的回归测试。

覆盖：
- 未修复库：切割点前记录按身份链改挂本人、离校旧主命名空间化、同号同人不动、
  切割点后记录原样
- 已归位库（存在 g<数字>- 作业记录）无 --backup 时拒跑
- --backup 重建模式幂等：重复运行 no-op，且与首次归位结果一致
"""
from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "reassign_homework_renumber.py"

CUTOFF = "2026-07-01"

_SCHEMA = """
CREATE TABLE teaching_class_member (student_id TEXT, name TEXT);
CREATE TABLE student_identity (id INTEGER PRIMARY KEY);
CREATE TABLE student_alias (student_id TEXT, identity_id INTEGER);
CREATE TABLE exam (id INTEGER PRIMARY KEY, grade INTEGER);
CREATE TABLE subject_score (student_id TEXT, exam_id INTEGER, name TEXT);
CREATE TABLE homework_record (id INTEGER PRIMARY KEY, student_id TEXT, date TEXT);
CREATE TABLE special_record (id INTEGER PRIMARY KEY, student_id TEXT, date TEXT);
"""


def _build_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    # 成员：B（改号后新号，高一旧号 A 已建链）、S（前后届同号同人）、
    # R（现成员的号被离校旧主复用：高一 R 的主人叫小戊，不是小丁）
    conn.executemany(
        "INSERT INTO teaching_class_member VALUES (?, ?)",
        [("B", "小甲"), ("S", "小丙"), ("R", "小丁")],
    )
    conn.execute("INSERT INTO student_identity VALUES (1)")
    conn.executemany(
        "INSERT INTO student_alias VALUES (?, ?)", [("B", 1), ("g1-A", 1)]
    )
    conn.execute("INSERT INTO exam VALUES (1, 1)")
    # 成绩学号宇宙：A（已建链旧号）、C（离校旧主）、S、B、R（复用号的离校旧主）
    conn.executemany(
        "INSERT INTO subject_score VALUES (?, 1, ?)",
        [
            ("g1-A", "小甲"),
            ("C", "小庚"),
            ("S", "小丙"),
            ("B", "小甲"),
            ("R", "小戊"),
        ],
    )
    # 作业记录：切割点前 A×2（应→B）、C×1（应→g1-C）、S×1（同号同人不动）、
    # B×1（本人不动）、R×1（复用号→离校旧主 g1-R）；切割点后 B×1（原样）
    conn.executemany(
        "INSERT INTO homework_record (student_id, date) VALUES (?, ?)",
        [
            ("A", "2026-03-01"),
            ("A", "2026-04-01"),
            ("C", "2026-05-01"),
            ("S", "2026-05-02"),
            ("B", "2026-05-03"),
            ("R", "2026-05-04"),
            ("B", "2026-08-01"),
        ],
    )
    conn.executemany(
        "INSERT INTO special_record (student_id, date) VALUES (?, ?)",
        [("A", "2026-04-03"), ("B", "2026-08-02")],
    )
    conn.commit()
    conn.close()


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
    )


def _counts(path: Path, table: str) -> dict:
    conn = sqlite3.connect(path)
    rows = conn.execute(
        f"SELECT student_id, COUNT(*) FROM {table} GROUP BY student_id"
    ).fetchall()
    conn.close()
    return dict(rows)


def test_first_run_reassigns_and_rerun_refuses(tmp_path):
    db = tmp_path / "db.sqlite"
    _build_db(db)
    snapshot = tmp_path / "before.sqlite"
    shutil.copy(db, snapshot)

    proc = _run(["--db", str(db), "--cutoff", CUTOFF])
    assert proc.returncode == 0, proc.stdout
    hw = _counts(db, "homework_record")
    assert hw.get("B") == 4, hw  # 自己的 2 条 + A 改挂 2 条
    assert hw.get("g1-C") == 1, hw  # 离校旧主命名空间化
    assert hw.get("g1-R") == 1, hw  # 复用号的离校旧主按姓名判别命名空间化
    assert hw.get("S") == 1, hw  # 同号同人不动
    assert "A" not in hw and "C" not in hw and "R" not in hw, hw
    sp = _counts(db, "special_record")
    assert sp.get("B") == 2 and sp.get("g1-C") is None, sp

    # 已归位库无 --backup 拒跑
    proc2 = _run(["--db", str(db), "--cutoff", CUTOFF])
    assert proc2.returncode != 0, proc2.stdout
    assert "拒跑" in proc2.stdout, proc2.stdout
    assert _counts(db, "homework_record") == hw  # 拒跑不写库


def test_backup_rebuild_is_idempotent(tmp_path):
    db = tmp_path / "db.sqlite"
    _build_db(db)
    snapshot = tmp_path / "before.sqlite"
    shutil.copy(db, snapshot)

    first = _run(["--db", str(db), "--cutoff", CUTOFF])
    assert first.returncode == 0, first.stdout
    after_first = _counts(db, "homework_record")

    # 重建模式：从修复前快照推导权威值，结果与首次归位一致
    proc = _run(["--db", str(db), "--cutoff", CUTOFF, "--backup", str(snapshot)])
    assert proc.returncode == 0, proc.stdout
    assert "待改写 0 行" in proc.stdout, proc.stdout
    assert _counts(db, "homework_record") == after_first

    # 在未修复库上直接用重建模式（备份=当前库）等价于首次归位
    db2 = tmp_path / "db2.sqlite"
    _build_db(db2)
    snap2 = tmp_path / "before2.sqlite"
    shutil.copy(db2, snap2)
    proc2 = _run(["--db", str(db2), "--cutoff", CUTOFF, "--backup", str(snap2)])
    assert proc2.returncode == 0, proc2.stdout
    assert _counts(db2, "homework_record") == after_first


def test_dry_run_does_not_write(tmp_path):
    db = tmp_path / "db.sqlite"
    _build_db(db)
    before = _counts(db, "homework_record")
    proc = _run(["--db", str(db), "--cutoff", CUTOFF, "--dry-run"])
    assert proc.returncode == 0, proc.stdout
    assert "dry-run" in proc.stdout
    assert _counts(db, "homework_record") == before
