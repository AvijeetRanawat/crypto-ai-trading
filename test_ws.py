import asyncio
from api_client import client
from logger import logger

async def test_ws():
    logger.info("Testing WebSocket (Socket.io) connectivity...")
    # Subscribe to BTCUSDT and ETHUSDT
    channels = ["BTCUSDT", "ETHUSDT"]
    
    # Run the listener in the background
    listener = asyncio.create_task(client.connect_ws(channels))
    
    logger.info("Waiting for data (15 seconds)...")
    for _ in range(15):
        await asyncio.sleep(1)
        if client.latest_prices:
            logger.info(f"Received Prices: {client.latest_prices}")
            break
    else:
        logger.error("No WebSocket data received.")
        
    listener.cancel()
    try:
        await listener
    except asyncio.CancelledError:
        pass

if __name__ == "__main__":
    asyncio.run(test_ws())
