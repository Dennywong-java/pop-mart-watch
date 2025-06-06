"""
主程序入口
"""
import asyncio
import logging
from src.config import Config
from src.discord_bot import DiscordBot

logger = logging.getLogger(__name__)

async def run_bot(config: Config):
    """运行 Discord 机器人"""
    bot = DiscordBot(config)
    await bot.start(config.discord.token)

def main():
    """主函数"""
    try:
        # 加载配置
        config = Config.load()
        
        # 运行机器人
        asyncio.run(run_bot(config))
    except Exception as e:
        logger.error(f"程序运行出错: {str(e)}")
        raise

if __name__ == "__main__":
    main() 