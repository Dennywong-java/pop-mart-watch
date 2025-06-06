"""
主程序入口
"""
import asyncio
import logging.config
from src.config import Config
from src.discord_bot import run_bot

if __name__ == "__main__":
    config = Config()
    asyncio.run(run_bot(config)) 