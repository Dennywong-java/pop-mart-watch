"""
Discord 机器人模块，处理 Discord 相关功能
"""
import asyncio
import logging
import discord
from discord import app_commands
from discord.ext import commands, tasks
import aiohttp
from typing import Optional, Dict, List, Any
from urllib.parse import urlparse
import json
import os
import traceback
from datetime import datetime

from src.config import Config
from src.monitor import Monitor

logger = logging.getLogger(__name__)

class DiscordBot(discord.Client):
    """Discord 机器人类"""
    
    def __init__(self, config: Config):
        """初始化 Discord 机器人"""
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        
        self.config = config
        self.tree = app_commands.CommandTree(self)
        self.monitor = Monitor()
        self.monitored_items = {}
        self.load_monitored_items()
        
        # 注册命令
        self.setup_commands()
        
    def setup_commands(self):
        """设置斜杠命令"""
        @self.tree.command(
            name="watch",
            description="添加商品到监控列表"
        )
        async def watch(interaction: discord.Interaction, url: str, name: str):
            try:
                # 验证 URL
                if not any(domain in url for domain in self.config.monitor.allowed_domains):
                    await interaction.response.send_message(
                        f"不支持的域名。允许的域名: {', '.join(self.config.monitor.allowed_domains)}"
                    )
                    return
                
                # 添加到监控列表
                self.monitored_items[url] = {
                    'name': name,
                    'url': url,
                    'last_status': None
                }
                self.save_monitored_items()
                
                await interaction.response.send_message(f"已添加商品到监控列表: {name}")
                logger.info(f"添加商品到监控列表: {name} ({url})")
                
            except Exception as e:
                logger.error(f"添加监控商品时出错: {str(e)}")
                await interaction.response.send_message(f"添加监控商品时出错: {str(e)}")
        
        @self.tree.command(
            name="unwatch",
            description="从监控列表中移除商品"
        )
        async def unwatch(interaction: discord.Interaction, url: str):
            try:
                if url in self.monitored_items:
                    name = self.monitored_items[url]['name']
                    del self.monitored_items[url]
                    self.save_monitored_items()
                    await interaction.response.send_message(f"已从监控列表移除商品: {name}")
                    logger.info(f"从监控列表移除商品: {name} ({url})")
                else:
                    await interaction.response.send_message("该商品不在监控列表中")
            except Exception as e:
                logger.error(f"移除监控商品时出错: {str(e)}")
                await interaction.response.send_message(f"移除监控商品时出错: {str(e)}")
        
        @self.tree.command(
            name="list",
            description="显示所有正在监控的商品"
        )
        async def list_items(interaction: discord.Interaction):
            try:
                await interaction.response.defer()
                
                if not self.monitored_items:
                    await interaction.followup.send("监控列表为空")
                    return
                
                # 构建消息
                message = "正在监控的商品:\n"
                for url, item in self.monitored_items.items():
                    message += f"- {item['name']}\n  {url}\n"
                
                await interaction.followup.send(message)
                
            except Exception as e:
                logger.error(f"显示监控列表时出错: {str(e)}")
                await interaction.followup.send(f"显示监控列表时出错: {str(e)}")
        
        @self.tree.command(
            name="status",
            description="显示机器人状态"
        )
        async def status(interaction: discord.Interaction):
            try:
                await interaction.response.send_message(
                    f"机器人状态: 正常运行中\n"
                    f"监控商品数量: {len(self.monitored_items)}\n"
                    f"检查间隔: {self.config.monitor.check_interval} 秒"
                )
            except Exception as e:
                logger.error(f"显示状态时出错: {str(e)}")
                await interaction.response.send_message(f"显示状态时出错: {str(e)}")
    
    async def setup_hook(self):
        """设置钩子"""
        logger.info("初始化 Discord 机器人...")
        
        # 同步命令到服务器
        try:
            await self.tree.sync(guild=discord.Object(id=self.config.discord.guild_id))
            commands = await self.tree.fetch_commands(guild=discord.Object(id=self.config.discord.guild_id))
            logger.info(f"斜杠命令已同步到服务器 {self.config.discord.guild_id}，共 {len(commands)} 个命令")
            for command in commands:
                logger.info(f"已注册命令: /{command.name} - {command.description}")
        except Exception as e:
            logger.error(f"同步命令时出错: {str(e)}")
            return
        
        logger.info("机器人设置完成")
    
    async def on_ready(self):
        """机器人就绪事件处理"""
        logger.info(f"机器人已登录: {self.user.name}")
        
        # 启动监控任务
        self.monitor_task = self.loop.create_task(self.monitor_products())
        logger.info("商品监控任务已启动")
    
    def load_monitored_items(self):
        """从文件加载监控商品列表"""
        try:
            if os.path.exists(self.config.storage.data_file):
                with open(self.config.storage.data_file, 'r', encoding='utf-8') as f:
                    self.monitored_items = json.load(f)
        except Exception as e:
            logger.error(f"加载监控商品列表时出错: {str(e)}")
    
    def save_monitored_items(self):
        """保存监控商品列表到文件"""
        try:
            os.makedirs(os.path.dirname(self.config.storage.data_file), exist_ok=True)
            with open(self.config.storage.data_file, 'w', encoding='utf-8') as f:
                json.dump(self.monitored_items, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存监控商品列表时出错: {str(e)}")
    
    async def monitor_products(self):
        """监控商品状态"""
        while True:
            try:
                for url, item in self.monitored_items.items():
                    try:
                        # 检查商品状态
                        is_available = await self.monitor.check_product_availability_with_delay(
                            url, self.config.monitor.request_delay
                        )
                        
                        # 如果状态改变，发送通知
                        if is_available != item.get('last_status'):
                            item['last_status'] = is_available
                            self.save_monitored_items()
                            
                            status = "可购买" if is_available else "已售罄"
                            message = f"商品状态更新:\n{item['name']}\n状态: {status}\n{url}"
                            
                            await self.send_notification(message)
                            
                    except Exception as e:
                        logger.error(f"监控商品时出错 {item['name']}: {str(e)}")
                
                # 等待下一次检查
                await asyncio.sleep(self.config.monitor.check_interval)
                
            except Exception as e:
                logger.error(f"监控任务出错: {str(e)}")
                await asyncio.sleep(60)  # 出错后等待一分钟再继续
    
    async def send_notification(self, message: str):
        """发送通知消息到指定频道"""
        try:
            channel = self.get_channel(self.config.discord.channel_id)
            if channel:
                await channel.send(message)
            else:
                logger.error(f"无法找到通知频道: {self.config.discord.channel_id}")
        except Exception as e:
            logger.error(f"发送通知消息时出错: {str(e)}")
    
    async def on_error(self, event, *args, **kwargs):
        """错误处理"""
        logger.error(f"事件处理出错 {event}: {str(args)} {str(kwargs)}")
    
    async def on_command_error(self, ctx, error):
        """命令错误处理"""
        logger.error(f"命令执行出错: {str(error)}")
        await ctx.send(f"命令执行出错: {str(error)}")

async def run_bot(config: Config):
    """运行 Discord 机器人"""
    try:
        async with DiscordBot(config) as bot:
            await bot.start(config.discord_token)
    except Exception as e:
        logger.error(f"运行机器人时出错: {str(e)}")
        raise