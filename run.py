import multiprocessing
import uvicorn
import asyncio
import main
from dashboard_api import app
from logger import logger

def run_dashboard():
    logger.info("Starting Dashboard Backend on http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")

async def run_agent():
    logger.info("Starting Trading Agent...")
    await main.main()

def start_agent_loop():
    asyncio.run(run_agent())

if __name__ == "__main__":
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
