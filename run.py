import asyncio
import multiprocessing
import os
import time
from datetime import datetime
from typing import Dict, Tuple

import uvicorn

from logger import logger


def run_dashboard():
    from dashboard_api import app

    logger.info("Starting Dashboard Backend on http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")


async def run_agent():
    import main as main_module

    logger.info("Starting Trading Agent...")
    await main_module.main()


def start_agent_loop():
    asyncio.run(run_agent())


def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _snapshot_backend_files(root_dir: str) -> Dict[str, int]:
    """Return path -> mtime_ns for backend-relevant files."""
    ignore_dirs = {
        ".git",
        ".venv",
        "frontend/node_modules",
        "frontend/dist",
        "static/dist",
        "__pycache__",
    }
    tracked_names = {".env", ".env.template"}
    tracked_exts = {".py"}

    snapshot: Dict[str, int] = {}
    for dirpath, dirnames, filenames in os.walk(root_dir):
        rel_dir = os.path.relpath(dirpath, root_dir)
        rel_dir_norm = rel_dir.replace("\\", "/")

        # Prune ignored directories early.
        dirnames[:] = [
            d for d in dirnames
            if os.path.join(rel_dir_norm, d).replace("\\", "/") not in ignore_dirs and d not in ignore_dirs
        ]

        for name in filenames:
            path = os.path.join(dirpath, name)
            rel_path = os.path.relpath(path, root_dir).replace("\\", "/")
            if any(rel_path.startswith(f"{p}/") for p in ignore_dirs):
                continue
            if name in tracked_names or os.path.splitext(name)[1] in tracked_exts:
                try:
                    snapshot[path] = os.stat(path).st_mtime_ns
                except FileNotFoundError:
                    continue
    return snapshot


def _start_children() -> Tuple[multiprocessing.Process, multiprocessing.Process]:
    p1 = multiprocessing.Process(target=run_dashboard)
    p2 = multiprocessing.Process(target=start_agent_loop)
    p1.start()
    p2.start()
    return p1, p2


def _stop_children(*procs: multiprocessing.Process):
    for p in procs:
        if p.is_alive():
            p.terminate()
    for p in procs:
        p.join(timeout=5)


def _supervise(auto_restart: bool, root_dir: str):
    p1, p2 = _start_children()
    if not auto_restart:
        p1.join()
        p2.join()
        return

    logger.info("Auto-restart watcher enabled for backend file changes.")
    last_snapshot = _snapshot_backend_files(root_dir)

    while True:
        time.sleep(1)

        if not p1.is_alive() or not p2.is_alive():
            logger.warning("One child process exited. Stopping both.")
            _stop_children(p1, p2)
            break

        current_snapshot = _snapshot_backend_files(root_dir)
        if current_snapshot != last_snapshot:
            logger.info("Detected backend file change. Restarting dashboard + agent...")
            _stop_children(p1, p2)
            p1, p2 = _start_children()
            last_snapshot = current_snapshot


if __name__ == "__main__":
    import sys

    # Shared runtime session id for all child processes (engine + dashboard).
    os.environ["TRADING_SESSION_ID"] = datetime.now().strftime("%Y%m%dT%H%M%S")

    # ── PID Lock: prevent multiple instances running simultaneously ──
    root = os.path.dirname(os.path.abspath(__file__))
    pid_file = os.path.join(root, "run.pid")
    if os.path.exists(pid_file):
        with open(pid_file) as f:
            old_pid = f.read().strip()
        # Check if that PID is actually still running
        try:
            os.kill(int(old_pid), 0)
            print(f"❌ Another instance is already running (PID {old_pid}). Kill it first: kill -9 {old_pid}")
            sys.exit(1)
        except (ProcessLookupError, ValueError):
            pass  # PID is stale — safe to proceed

    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))

    # ── Clear log on every restart ──
    log_path = os.path.join(root, "trading.log")
    with open(log_path, "w") as f:
        f.write(f"=== Session started {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    print(f"🗑  Log cleared. PID {os.getpid()} locked. Fresh session starting...")

    # Ensure latest DB schema (migrations) exists before reset/start.
    from database import init_db

    init_db()

    # ── Reset Session Data ──
    from reset_session import reset_session

    reset_session()

    auto_restart = _env_bool("AUTO_RESTART_ON_BACKEND_CHANGES", True)

    try:
        _supervise(auto_restart=auto_restart, root_dir=root)
    except KeyboardInterrupt:
        logger.info("Shutting down processes...")
    finally:
        # Release the PID lock on exit
        try:
            os.remove(pid_file)
        except FileNotFoundError:
            pass
