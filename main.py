import asyncio
import signal
from api_client import client
from engine import TradingEngine
from config import config
from logger import logger
from database import init_db

async def main():
    logger.info(f"Initializing {config.EXCHANGE} Trading Agent with WebSocket support...")
    init_db()

    engine = TradingEngine(client)

    # Use blue-chip whitelist as channels
    channels = config.BLUE_CHIP_WHITELIST

    loop = asyncio.get_running_loop()

    def _graceful_shutdown():
        """Cancel all running tasks so asyncio can flush DB writes before exit."""
        logger.info("Shutdown signal received — cancelling engine tasks gracefully...")
        for task in asyncio.all_tasks(loop):
            if not task.done():
                task.cancel()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _graceful_shutdown)
        except (NotImplementedError, OSError):
            pass  # non-main-thread or Windows fallback

    try:
        # Run all tasks concurrently (shared balance across modes).
        coros = [
            client.poll_prices(channels),
            engine.run_loop("SPOT"),
            engine.run_loop("FUTURES"),
            engine.run_loop("OPTIONS"),
        ]
        if config.ENABLE_PERIODIC_REVIEW:
            coros.append(engine._periodic_self_improvement_loop())
        await asyncio.gather(*coros)
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Shutdown requested — engine stopped cleanly.")
    except Exception as e:
        logger.error(f"Unexpected error in main loop: {e}")
    finally:
        logger.info("Engine exiting. All DB state already persisted via simulator.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
