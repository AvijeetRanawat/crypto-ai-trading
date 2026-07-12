import multiprocessing
import uvicorn
import asyncio
import time
from logger import logger

def run_dashboard():
    try:
        from dashboard_api import app
        logger.info("Starting Dashboard Backend on http://127.0.0.1:8000")
        uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
    except Exception as e:
        logger.error(f"Dashboard process crashed: {e}", exc_info=True)
        raise

async def run_agent():
    try:
        import main as main_module
        logger.info("Starting Trading Agent...")
        await main_module.main()
    except Exception as e:
        logger.error(f"Trading agent crashed: {e}", exc_info=True)
        raise

def start_agent_loop():
    try:
        asyncio.run(run_agent())
    except Exception:
        raise


def _start_child(kind: str, ctx):
    if kind == "dashboard":
        p = ctx.Process(target=run_dashboard, name="dashboard")
    elif kind == "agent":
        p = ctx.Process(target=start_agent_loop, name="agent")
    else:
        raise ValueError(f"Unknown child kind: {kind}")
    p.start()
    logger.info(f"Spawned {kind} process pid={p.pid}")
    return p

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
        except PermissionError:
            # In restricted environments, kill(0) can be denied even for stale PIDs.
            # Fall back to replacing stale lock so the system can start.
            logger.warning(f"PID lock check permission denied for PID {old_pid}; replacing stale lock.")
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

    # Use spawn for stable child-process behavior across platforms.
    ctx = multiprocessing.get_context("spawn")
    children = {
        "dashboard": _start_child("dashboard", ctx),
        "agent": _start_child("agent", ctx),
    }
    restart_times = {"dashboard": [], "agent": []}
    restart_window_secs = 300
    max_restarts_in_window = 5

    try:
        while True:
            time.sleep(5)
            for kind, proc in list(children.items()):
                if proc.is_alive():
                    continue

                code = proc.exitcode
                logger.error(f"{kind} process exited (pid={proc.pid}, code={code}). Restarting...")
                now = time.time()
                recent = [t for t in restart_times[kind] if now - t <= restart_window_secs]
                recent.append(now)
                restart_times[kind] = recent
                if len(recent) > max_restarts_in_window:
                    logger.error(
                        f"{kind} restart limit exceeded ({len(recent)} in {restart_window_secs}s). "
                        "Shutting down supervisor."
                    )
                    raise RuntimeError(f"{kind} restart loop detected")

                children[kind] = _start_child(kind, ctx)
    except KeyboardInterrupt:
        logger.info("Shutting down processes...")
    except Exception as e:
        logger.error(f"Supervisor exiting due to fatal error: {e}", exc_info=True)
    finally:
        for proc in children.values():
            try:
                if proc.is_alive():
                    proc.terminate()
            except Exception:
                pass
        # Release the PID lock on exit
        try:
            os.remove(pid_file)
        except FileNotFoundError:
            pass
