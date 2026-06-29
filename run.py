#!/usr/bin/env python3
"""跨平台启动器：start / stop / init 三个子命令。

macOS 与 Windows 双平台共用此文件；薄包装脚本（.sh / .command / .bat）
只负责切到本目录然后调用 `python run.py <子命令>`。
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

IS_WINDOWS = sys.platform.startswith("win")

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR / "backend"
FRONTEND_DIR = APP_DIR / "frontend"
DATA_DIR = Path(os.environ.get("EXAM_TRACKER_DIR", str(Path.home() / ".exam-tracker")))
BACKUP_DIR = Path(os.environ.get("EXAM_TRACKER_BACKUP_DIR", str(Path.home() / ".exam-tracker-backups")))
BACKEND_LOG = DATA_DIR / "backend.log"
FRONTEND_LOG = DATA_DIR / "frontend.log"

BACKEND_PORT = 8000
FRONTEND_PORT = 3000


# ---------- 工具函数 ----------

def venv_python() -> Path:
    """返回 backend/.venv 内 python 解释器路径。"""
    if IS_WINDOWS:
        return BACKEND_DIR / ".venv" / "Scripts" / "python.exe"
    return BACKEND_DIR / ".venv" / "bin" / "python"


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def pids_on_port(port: int) -> list[int]:
    """返回监听 port 的进程 PID 列表（跨平台）。"""
    pids: set[int] = set()
    if IS_WINDOWS:
        try:
            out = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True, text=True, check=False,
            ).stdout
        except FileNotFoundError:
            return []
        needle = f":{port}"
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            # 列: Proto Local Foreign State PID
            local = parts[1]
            state = parts[3] if len(parts) >= 5 else ""
            if local.endswith(needle) and state.upper() == "LISTENING":
                try:
                    pids.add(int(parts[-1]))
                except ValueError:
                    pass
    else:
        try:
            out = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True, text=True, check=False,
            ).stdout
        except FileNotFoundError:
            return []
        for line in out.splitlines():
            line = line.strip()
            if line.isdigit():
                pids.add(int(line))
    return sorted(pids)


def kill_pid(pid: int, force: bool = False) -> None:
    if IS_WINDOWS:
        args = ["taskkill", "/PID", str(pid)]
        if force:
            args.insert(1, "/F")
        subprocess.run(args, capture_output=True, check=False)
    else:
        import signal
        try:
            os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError:
            pass


def kill_port(port: int) -> int:
    """停掉占用 port 的所有进程，返回被停掉的进程数。"""
    pids = pids_on_port(port)
    for pid in pids:
        kill_pid(pid, force=False)
    time.sleep(1)
    remaining = pids_on_port(port)
    for pid in remaining:
        kill_pid(pid, force=True)
    return len(pids)


def spawn_background(cmd, cwd: Path, log_path: Path, shell: bool = False) -> None:
    """启动后台进程，stdout/stderr 重定向到 log_path。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log = log_path.open("ab", buffering=0)
    kwargs = dict(
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        shell=shell,
    )
    if IS_WINDOWS:
        # DETACHED_PROCESS = 0x00000008, CREATE_NEW_PROCESS_GROUP = 0x00000200
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)


def run_foreground(cmd, cwd: Path, shell: bool = False) -> int:
    return subprocess.run(cmd, cwd=str(cwd), shell=shell).returncode


# ---------- 子命令 ----------

def cmd_start() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "raw").mkdir(parents=True, exist_ok=True)

    print("=== 成绩追踪 Web App 启动 ===")

    # 后端
    if port_in_use(BACKEND_PORT):
        print(f"[警告] 端口 {BACKEND_PORT} 已被占用，后端可能已在运行")
    else:
        print(f"[1/3] 启动 FastAPI 后端 (localhost:{BACKEND_PORT})...")
        if not venv_python().exists():
            print("  首次启动：创建 backend/.venv 并安装依赖...")
            rc = run_foreground([sys.executable, "-m", "venv", ".venv"], cwd=BACKEND_DIR)
            if rc != 0:
                print("创建虚拟环境失败")
                return rc
            run_foreground([str(venv_python()), "-m", "pip", "install", "--upgrade", "pip"], cwd=BACKEND_DIR)
            rc = run_foreground([str(venv_python()), "-m", "pip", "install", "-e", "."], cwd=BACKEND_DIR)
            if rc != 0:
                print("pip install -e . 失败")
                return rc
        spawn_background(
            [str(venv_python()), "-m", "uvicorn", "app.main:app",
             "--host", "0.0.0.0", "--port", str(BACKEND_PORT)],
            cwd=BACKEND_DIR,
            log_path=BACKEND_LOG,
        )
        time.sleep(2)

    # 前端
    if port_in_use(FRONTEND_PORT):
        print(f"[警告] 端口 {FRONTEND_PORT} 已被占用，前端可能已在运行")
    else:
        print(f"[2/3] 启动 Next.js 前端 (localhost:{FRONTEND_PORT})...")
        if not (FRONTEND_DIR / "node_modules").exists():
            print("  首次启动：安装前端依赖 (npm install)...")
            rc = run_foreground("npm install", cwd=FRONTEND_DIR, shell=True)
            if rc != 0:
                print("npm install 失败")
                return rc
        # Windows 上 npm 是 npm.cmd，借 shell=True 让 PATH 解析
        spawn_background(
            "npm run dev",
            cwd=FRONTEND_DIR,
            log_path=FRONTEND_LOG,
            shell=True,
        )
        time.sleep(3)

    print("[3/3] 打开浏览器...")
    time.sleep(1)
    webbrowser.open(f"http://localhost:{FRONTEND_PORT}")

    print()
    print("=== 启动完成 ===")
    print(f"后端: http://localhost:{BACKEND_PORT}")
    print(f"前端: http://localhost:{FRONTEND_PORT}")
    print()
    print("关闭服务：双击「停止成绩分析」脚本，或 `python run.py stop`")
    return 0


def cmd_stop() -> int:
    print("=== 成绩追踪 Web App 停止 ===")
    any_stopped = False
    for port in (BACKEND_PORT, FRONTEND_PORT):
        pids = pids_on_port(port)
        if not pids:
            print(f"端口 {port} 未发现运行中的服务")
            continue
        print(f"停止端口 {port} 上的进程: {pids}")
        kill_port(port)
        any_stopped = True
    if any_stopped:
        print("已停止成绩分析应用。")
    else:
        print("没有发现需要停止的成绩分析服务。")
    return 0


def make_backup(prefix: str = "backup") -> Path | None:
    """打包 db.sqlite + homework_exports/ 到 ~/.exam-tracker-backups（DATA_DIR 之外）。"""
    import zipfile

    db_path = DATA_DIR / "db.sqlite"
    export_dir = DATA_DIR / "homework_exports"
    if not db_path.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = BACKUP_DIR / f"{prefix}-{stamp}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(db_path, "db.sqlite")
        if export_dir.is_dir():
            for p in export_dir.rglob("*"):
                if p.is_file():
                    zf.write(p, str(Path("homework_exports") / p.relative_to(export_dir)))
    return out


def cmd_backup() -> int:
    out = make_backup()
    if out is None:
        print(f"没有可备份的数据库（{DATA_DIR / 'db.sqlite'} 不存在）。")
        return 1
    print(f"已备份到: {out}")
    return 0


def cmd_restore(filename: str | None) -> int:
    import zipfile

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backups = sorted(BACKUP_DIR.glob("*.zip"), reverse=True)
    if not backups:
        print(f"没有可用备份（{BACKUP_DIR} 为空）。")
        return 1
    target = (BACKUP_DIR / filename) if filename else backups[0]
    if not target.exists():
        print(f"备份不存在: {target}")
        print("可用备份：")
        for b in backups:
            print(f"  {b.name}")
        return 1
    with zipfile.ZipFile(target) as zf:
        if "db.sqlite" not in zf.namelist():
            print("备份内缺少 db.sqlite")
            return 1
    # 恢复前先快照当前库
    make_backup(prefix="before-restore")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target) as zf, open(DATA_DIR / "db.sqlite", "wb") as dst:
        with zf.open("db.sqlite") as src:
            shutil.copyfileobj(src, dst)
    print(f"已从 {target.name} 恢复数据库。请重新启动应用。")
    return 0


def cmd_init() -> int:
    print("=== 成绩追踪 Web App 全新初始化 ===")
    print("这会清空本应用的本地数据库、已上传表格、日志和旧备份。")
    print("保留项目代码和 backend/.env 配置文件。")
    print()

    print("[1/4] 停止正在运行的服务...")
    for port in (BACKEND_PORT, FRONTEND_PORT):
        pids = pids_on_port(port)
        if pids:
            print(f"  停止端口 {port} 上的进程: {pids}")
            kill_port(port)

    print()
    snapshot = make_backup(prefix="before-init")
    if snapshot is not None:
        print(f"[安全快照] 清空前已自动备份到: {snapshot}")
    print(f"[2/4] 清空本地应用数据 ({DATA_DIR})...")
    shutil.rmtree(DATA_DIR, ignore_errors=True)
    (DATA_DIR / "raw").mkdir(parents=True, exist_ok=True)

    print()
    print("[3/4] 重建后端 Python 环境...")
    venv_dir = BACKEND_DIR / ".venv"
    shutil.rmtree(venv_dir, ignore_errors=True)
    rc = run_foreground([sys.executable, "-m", "venv", ".venv"], cwd=BACKEND_DIR)
    if rc != 0:
        print("创建虚拟环境失败")
        return rc
    run_foreground([str(venv_python()), "-m", "pip", "install", "--upgrade", "pip"], cwd=BACKEND_DIR)
    rc = run_foreground([str(venv_python()), "-m", "pip", "install", "-e", "."], cwd=BACKEND_DIR)
    if rc != 0:
        print("pip install -e . 失败")
        return rc

    print()
    print("[4/4] 重建前端 npm 环境...")
    shutil.rmtree(FRONTEND_DIR / "node_modules", ignore_errors=True)
    shutil.rmtree(FRONTEND_DIR / ".next", ignore_errors=True)
    rc = run_foreground("npm install", cwd=FRONTEND_DIR, shell=True)
    if rc != 0:
        print("npm install 失败")
        return rc

    # macOS：给 .sh / .command 加可执行位（Windows 不需要）
    if not IS_WINDOWS:
        for name in ("start.sh", "启动成绩分析.command",
                     "停止成绩分析.command", "初始化成绩分析.command"):
            p = APP_DIR / name
            if p.exists():
                try:
                    p.chmod(p.stat().st_mode | 0o111)
                except OSError:
                    pass

    print()
    print("=== 全新初始化完成 ===")
    print(f"已清空: {DATA_DIR}")
    print("已重建: backend/.venv")
    print("已重建: frontend/node_modules")
    print()
    print("下一步：双击「启动成绩分析」脚本启动一个干净的新应用。")
    return 0


# ---------- 入口 ----------

def main() -> int:
    parser = argparse.ArgumentParser(prog="run.py", description="成绩分析 webapp 跨平台启动器")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("start", help="启动后端 + 前端 + 浏览器")
    sub.add_parser("stop", help="停止后端 + 前端")
    sub.add_parser("init", help="清空数据并重建 venv / node_modules")
    sub.add_parser("backup", help="备份数据库到 ~/.exam-tracker-backups")
    p_restore = sub.add_parser("restore", help="从备份恢复数据库（不指定则用最新）")
    p_restore.add_argument("filename", nargs="?", help="备份文件名；省略则用最新一份")
    args = parser.parse_args()

    if args.cmd == "start":
        return cmd_start()
    if args.cmd == "stop":
        return cmd_stop()
    if args.cmd == "init":
        return cmd_init()
    if args.cmd == "backup":
        return cmd_backup()
    if args.cmd == "restore":
        return cmd_restore(args.filename)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
