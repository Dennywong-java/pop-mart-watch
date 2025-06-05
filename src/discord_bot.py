"""
Discord 机器人模块，处理 Discord 相关功能
"""
import asyncio
import logging
import discord
from discord.ext import commands
import aiohttp
from typing import Optional, Dict
from urllib.parse import urlparse
from datetime import datetime

from src.config import config
from src.storage import MonitorStore
from src.monitor import ProductMonitor

logger = logging.getLogger(__name__)

class MonitorBot(commands.Bot):
    """
    监控机器人类
    继承自 discord.ext.commands.Bot
    """
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=config.command_prefix, intents=intents)
        
        self.store = MonitorStore()
        self.monitor = ProductMonitor()
        self.bg_task = None
        
        # 注册命令
        self.setup_commands()

    async def _monitor_products(self):
        """
        商品监控后台任务
        定期检查所有商品的可用性状态
        """
        await self.wait_until_ready()
        channel = self.get_channel(config.discord_channel_id)
        
        if not channel:
            logger.error(f"Could not find channel with ID {config.discord_channel_id}")
            return
            
        logger.info("Starting product monitoring...")
        
        while not self.is_closed():
            try:
                async with aiohttp.ClientSession() as session:
                    items = self.store.get_items()
                    for item in items:
                        url = item.get('url')
                        if not url:
                            continue
                            
                        available = await self.monitor.monitor_with_delay(url, session)
                        
                        if available is not None:
                            previous_status = item.get('status', 'unknown')
                            current_status = "available" if available else "sold_out"
                            
                            if previous_status != current_status:
                                item['status'] = current_status
                                self.store.save_items()
                                await self.send_notification(channel, item, current_status)
                
                await asyncio.sleep(config.check_interval)
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {str(e)}")
                await asyncio.sleep(config.check_interval)

    async def send_notification(self, channel: discord.TextChannel, item: Dict, status: str):
        """
        发送状态变更通知
        
        Args:
            channel: Discord频道
            item: 商品信息
            status: 新状态
        """
        title = "🟢 商品可购买" if status == "available" else "🔴 商品已售罄"
        color = discord.Color.green() if status == "available" else discord.Color.red()
        
        embed = discord.Embed(
            title=title,
            description=f"**商品链接**：\n{item['url']}",
            color=color,
            timestamp=datetime.utcnow()
        )
        
        if item.get('name'):
            embed.add_field(name="商品名称", value=item['name'], inline=False)
            
        if item.get('image_url'):
            embed.set_image(url=item['image_url'])
            
        await channel.send(embed=embed)

    def setup_commands(self):
        """设置命令处理器"""
        @self.event
        async def on_ready():
            """机器人启动时的处理"""
            logger.info(f'{self.user} has connected to Discord!')
            if not self.bg_task:
                self.bg_task = self.loop.create_task(self._monitor_products())

        @self.command(name='watch')
        async def watch(ctx, url: str):
            """
            添加商品到监控列表
            
            Args:
                ctx: Discord上下文
                url: 商品URL
            """
            # 验证URL域名
            domain = urlparse(url).netloc
            if not any(allowed_domain in domain for allowed_domain in config.allowed_domains):
                await ctx.send("⚠️ 只支持监控 Pop Mart 网站的商品！")
                return
            
            # 解析商品信息
            product_info = self.monitor.parse_product_url(url)
            if not product_info:
                await ctx.send("⚠️ 无效的商品链接！")
                return
            
            # 获取商品详细信息
            async with aiohttp.ClientSession() as session:
                details = await self.monitor.get_product_info(url, session)
                if details:
                    product_info.update(details)
            
            # 添加商品到监控列表
            if self.store.add_item(product_info):
                embed = discord.Embed(
                    title="✅ 添加监控成功",
                    description=f"已添加商品到监控列表：\n{url}",
                    color=discord.Color.green()
                )
                
                # 添加商品标题
                if product_info.get('title'):
                    embed.add_field(
                        name="商品名称",
                        value=product_info['title'],
                        inline=False
                    )
                
                # 添加商品图片
                if product_info.get('image_url'):
                    embed.set_image(url=product_info['image_url'])
                
                logger.info(f"Added new item to watch: {url}")
            else:
                embed = discord.Embed(
                    title="⚠️ 添加失败",
                    description="该商品已在监控列表中",
                    color=discord.Color.red()
                )
                
                # 添加商品标题
                if product_info.get('title'):
                    embed.add_field(
                        name="商品名称",
                        value=product_info['title'],
                        inline=False
                    )
                
                # 添加商品图片
                if product_info.get('image_url'):
                    embed.set_image(url=product_info['image_url'])
                
                logger.warning(f"Attempted to add duplicate item: {url}")
            
            await ctx.send(embed=embed)

        @self.command(name='unwatch')
        async def unwatch(ctx, url: str):
            """
            从监控列表中移除商品
            
            Args:
                ctx: Discord上下文
                url: 商品URL
            """
            # 解析商品ID
            product_info = self.monitor.parse_product_url(url)
            if not product_info:
                await ctx.send("⚠️ 无效的商品链接！")
                return
            
            if self.store.remove_item(product_info['id']):
                embed = discord.Embed(
                    title="✅ 移除成功",
                    description=f"已从监控列表中移除商品：\n{url}",
                    color=discord.Color.green()
                )
                
                # 添加商品标题
                if product_info.get('title'):
                    embed.add_field(
                        name="商品名称",
                        value=product_info['title'],
                        inline=False
                    )
                
                logger.info(f"Removed item from watch: {url}")
            else:
                embed = discord.Embed(
                    title="⚠️ 移除失败",
                    description="该商品不在监控列表中",
                    color=discord.Color.red()
                )
            
            await ctx.send(embed=embed)

        @self.command(name='list')
        async def list_items(ctx):
            """显示所有正在监控的商品"""
            items = self.store.get_items()
            if not items:
                embed = discord.Embed(
                    title="监控列表",
                    description="目前没有监控任何商品",
                    color=discord.Color.blue()
                )
                await ctx.send(embed=embed)
                return
            
            for item in items:
                status = item.get('status', 'unknown')
                embed = discord.Embed(
                    title="🔍 监控商品",
                    description=f"**商品链接**：\n{item['url']}\n\n**状态**：{'可购买' if status == 'available' else '售罄'}",
                    color=discord.Color.green() if status == 'available' else discord.Color.red()
                )
                
                # 添加商品标题
                if item.get('title'):
                    embed.add_field(
                        name="商品名称",
                        value=item['title'],
                        inline=False
                    )
                
                # 添加商品图片
                if item.get('image_url'):
                    embed.set_image(url=item['image_url'])
                
                await ctx.send(embed=embed)

        @self.command(name='status')
        async def status(ctx):
            """显示机器人状态"""
            items = self.store.get_items()
            embed = discord.Embed(
                title="机器人状态",
                color=discord.Color.blue()
            )
            embed.add_field(name="监控商品数量", value=str(len(items)), inline=False)
            embed.add_field(name="检查间隔", value=f"{config.check_interval}秒", inline=False)
            embed.add_field(name="运行状态", value="🟢 正常运行中", inline=False)
            
            await ctx.send(embed=embed)

def run_bot():
    """运行Discord机器人"""
    bot = MonitorBot()
    bot.run(config.discord_token) 