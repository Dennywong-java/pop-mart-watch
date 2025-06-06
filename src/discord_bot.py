"""
Discord 机器人模块，处理 Discord 相关功能
"""
import asyncio
import logging
import discord
from discord import app_commands
from discord.ext import commands, tasks
import aiohttp
from typing import Optional, Dict, List
from urllib.parse import urlparse
import json
import os
import traceback
from datetime import datetime

from src.config import Config
from src.monitor import Monitor

logger = logging.getLogger(__name__)

class DiscordBot(commands.Bot):
    """
    监控机器人类
    继承自 commands.Bot
    """
    def __init__(self, config: Config):
        logger.info("初始化 Discord 机器人...")
        
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            description="Pop Mart 商品监控机器人"
        )
        
        self.config = config
        self.monitor = Monitor()
        self.monitoring_task = None
        self.session: Optional[aiohttp.ClientSession] = None

    async def setup_hook(self):
        """机器人启动时的设置"""
        try:
            # 注册命令
            await self._add_commands()
            
            # 创建 aiohttp 会话
            self.session = aiohttp.ClientSession()
            
            logger.info("机器人设置完成")
        except Exception as e:
            logger.error(f"机器人设置时出错: {str(e)}")
            raise

    async def _add_commands(self):
        """注册所有命令"""
        try:
            # 注册 watch 命令
            @self.tree.command(name='watch', description='添加商品到监控列表')
            async def watch(interaction: discord.Interaction, url: str):
                """添加商品到监控列表"""
                try:
                    # 验证URL域名
                    if not url.startswith('https://www.popmart.com'):
                        await interaction.response.send_message("⚠️ 只支持监控 Pop Mart 网站的商品！")
                        return

                    # 添加到监控列表
                    success = await self.monitor.add_monitored_item(url)
                    if success:
                        await interaction.response.send_message(f"✅ 已添加商品到监控列表: {url}")
                    else:
                        await interaction.response.send_message("❌ 添加失败，请检查URL是否正确")
                except Exception as e:
                    logger.error(f"添加监控商品时出错: {str(e)}")
                    await interaction.response.send_message("❌ 添加失败，发生错误")

            # 注册 unwatch 命令
            @self.tree.command(name='unwatch', description='从监控列表中移除商品')
            async def unwatch(interaction: discord.Interaction, url: str):
                """从监控列表中移除商品"""
                try:
                    success = await self.monitor.remove_monitored_item(url)
                    if success:
                        await interaction.response.send_message(f"✅ 已从监控列表移除商品: {url}")
                    else:
                        await interaction.response.send_message("❌ 移除失败，该商品可能不在监控列表中")
                except Exception as e:
                    logger.error(f"移除监控商品时出错: {str(e)}")
                    await interaction.response.send_message("❌ 移除失败，发生错误")

            # 注册 list 命令
            @self.tree.command(name='list', description='显示所有正在监控的商品')
            async def list_items(interaction: discord.Interaction):
                """显示所有正在监控的商品"""
                try:
                    items = self.monitor.load_monitored_items()
                    if not items:
                        await interaction.response.send_message("📝 监控列表为空")
                        return

                    embed = discord.Embed(
                        title="📋 监控商品列表",
                        color=discord.Color.blue(),
                        timestamp=datetime.utcnow()
                    )

                    for item in items:
                        status = "🟢 有库存" if item.get('last_status') else "🔴 售罄"
                        embed.add_field(
                            name=f"{item['name']} - {status}",
                            value=item['url'],
                            inline=False
                        )

                    await interaction.response.send_message(embed=embed)
                except Exception as e:
                    logger.error(f"获取监控列表时出错: {str(e)}")
                    await interaction.response.send_message("❌ 获取监控列表失败")

            # 注册 status 命令
            @self.tree.command(name='status', description='显示机器人状态')
            async def status(interaction: discord.Interaction):
                """显示机器人状态"""
                try:
                    embed = discord.Embed(
                        title="🤖 机器人状态",
                        color=discord.Color.blue(),
                        timestamp=datetime.utcnow()
                    )

                    # 添加基本信息
                    embed.add_field(
                        name="监控商品数量",
                        value=str(len(self.monitor.load_monitored_items())),
                        inline=True
                    )
                    embed.add_field(
                        name="检查间隔",
                        value=f"{self.config.request_delay}秒",
                        inline=True
                    )
                    embed.add_field(
                        name="运行状态",
                        value="🟢 正常运行" if self.monitoring_task and not self.monitoring_task.done() else "🔴 已停止",
                        inline=True
                    )

                    await interaction.response.send_message(embed=embed)
                except Exception as e:
                    logger.error(f"获取机器人状态时出错: {str(e)}")
                    await interaction.response.send_message("❌ 获取状态失败")

            # 同步命令到指定服务器或全局
            max_retries = 3
            retry_delay = 5  # 秒
            
            for attempt in range(max_retries):
                try:
                    if self.config.discord_guild_id:
                        # 同步到特定服务器
                        guild = discord.Object(id=self.config.discord_guild_id)
                        self.tree.copy_global_to(guild=guild)
                        commands = await self.tree.sync(guild=guild)
                        logger.info(f"斜杠命令已同步到服务器 {self.config.discord_guild_id}，共 {len(commands)} 个命令")
                    else:
                        # 全局同步
                        commands = await self.tree.sync()
                        logger.info(f"斜杠命令已全局同步，共 {len(commands)} 个命令")
                    
                    # 同步成功，打印已注册的命令
                    for cmd in commands:
                        logger.info(f"已注册命令: /{cmd.name} - {cmd.description}")
                    
                    break  # 如果成功，跳出重试循环
                    
                except discord.errors.Forbidden as e:
                    logger.error(f"同步命令时遇到权限错误: {str(e)}")
                    if attempt < max_retries - 1:
                        logger.info(f"等待 {retry_delay} 秒后重试...")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2  # 指数退避
                    else:
                        raise
                        
                except Exception as e:
                    logger.error(f"同步命令时出错: {str(e)}")
                    if attempt < max_retries - 1:
                        logger.info(f"等待 {retry_delay} 秒后重试...")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2  # 指数退避
                    else:
                        raise
                        
        except Exception as e:
            logger.error(f"注册命令时出错: {str(e)}")
            raise

    async def on_ready(self):
        """机器人就绪时的处理"""
        logger.info(f"机器人已登录: {self.user.name}")
        
        # 启动监控任务
        if not self.monitoring_task:
            self.monitoring_task = self.monitor_products.start()
            logger.info("商品监控任务已启动")

    async def close(self):
        """关闭机器人时的清理工作"""
        try:
            # 停止监控任务
            if self.monitoring_task:
                self.monitoring_task.cancel()
            
            # 关闭 aiohttp 会话
            if self.session:
                await self.session.close()
            
            await super().close()
        except Exception as e:
            logger.error(f"关闭机器人时出错: {str(e)}")
            raise

    @tasks.loop(seconds=30)
    async def monitor_products(self):
        """定期检查商品状态"""
        try:
            items = self.monitor.load_monitored_items()
            if not items:
                return
            
            for item in items:
                try:
                    # 检查商品状态
                    is_available = await self.monitor.check_product_availability_with_delay(
                        item['url'],
                        self.session
                    )
                    
                    # 如果状态发生变化，发送通知
                    if is_available is not None and is_available != item.get('last_status'):
                        item['last_status'] = is_available
                        self.monitor.save_monitored_items(items)
                        
                        # 准备通知消息
                        status = "有库存" if is_available else "已售罄"
                        message = f"商品状态更新:\n{item['name']}\n状态: {status}\n链接: {item['url']}"
                        
                        # 发送通知
                        channel = self.get_channel(self.config.notification_channel_id)
                        if channel:
                            await channel.send(message)
                            logger.info(f"已发送商品状态更新通知: {item['name']} - {status}")
                        else:
                            logger.error(f"无法找到通知频道: {self.config.notification_channel_id}")
                    
                except Exception as e:
                    logger.error(f"监控商品时出错 {item['name']}: {str(e)}")
                    continue
                
                # 添加延迟以避免请求过于频繁
                await asyncio.sleep(self.config.request_delay)
                
        except Exception as e:
            logger.error(f"执行监控任务时出错: {str(e)}")
    
    @monitor_products.before_loop
    async def before_monitor_products(self):
        """等待机器人就绪后再开始监控任务"""
        await self.wait_until_ready()
    
    async def on_command_error(self, ctx, error):
        """命令错误处理"""
        if isinstance(error, commands.errors.CommandNotFound):
            return
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