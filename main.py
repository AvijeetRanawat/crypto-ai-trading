import asyncio
from api_client import client
from engine import TradingEngine
from config import config
from logger import logger
from database import init_db

async def main():
    logger.info("Initializing CoinDCX Trading Agent with WebSocket support...")
    init_db()
    
    engine = TradingEngine(client)
    
    # Use blue-chip whitelist as channels
    channels = config.BLUE_CHIP_WHITELIST
    
    try:
        # Run all tasks concurrently
        tasks = [
            client.connect_ws(channels),
            engine.run_loop(),
        ]
        if config.ENABLE_PERIODIC_REVIEW:
            tasks.append(engine._periodic_self_improvement_loop())
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user.")
    except Exception as e:
        logger.error(f"Unexpected error in main loop: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
