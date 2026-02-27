import multiprocessing
import uvicorn
import asyncio
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

if __name__ == "__main__":
    import os, sys
    from datetime import datetime

    # Shared runtime session id for all child processes (engine + dashboard).
    os.environ["TRADING_SESSION_ID"] = datetime.now().strftime("%Y%m%dT%H%M%S")

    # ── PID Lock: prevent multiple instances running simultaneously ──
    pid_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run.pid")
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
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trading.log")
    with open(log_path, "w") as f:
        f.write(f"=== Session started {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    print(f"🗑  Log cleared. PID {os.getpid()} locked. Fresh session starting...")

    # Ensure latest DB schema (migrations) exists before reset/start.
    from database import init_db
    init_db()

    # ── Reset Session Data ──
    from reset_session import reset_session
    reset_session()

    p1 = multiprocessing.Process(target=run_dashboard)
    p2 = multiprocessing.Process(target=start_agent_loop)
    
    p1.start()
    p2.start()
    
    try:
        p1.join()
        p2.join()
    except KeyboardInterrupt:
        logger.info("Shutting down processes...")
        p1.terminate()
        p2.terminate()
    finally:
        # Release the PID lock on exit
        try:
            os.remove(pid_file)
        except FileNotFoundError:
            pass
