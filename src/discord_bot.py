"""
Discord 机器人模块，处理 Discord 相关功能
"""
import asyncio
import logging
import discord
from discord.ext import commands
import aiohttp
from typing import Optional
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

    async def send_notification(self, channel: discord.TextChannel, url: str, status_change: str):
        """
        发送商品状态变化通知
        
        Args:
            channel: Discord 频道
            url: 商品URL
            status_change: 状态变化类型 ('available' 或 'sold_out')
        """
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 获取商品信息
        async with aiohttp.ClientSession() as session:
            product_info = await self.monitor.get_product_info(url, session)
        
        if status_change == 'available':
            embed = discord.Embed(
                title="🎉 商品已上架！",
                description=f"发现时间：{current_time}\n\n**商品链接**：\n{url}",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            
            # 如果有商品标题，添加到通知中
            if product_info.get('title'):
                embed.add_field(
                    name="商品名称",
                    value=product_info['title'],
                    inline=False
                )
            
            embed.add_field(
                name="操作提示",
                value="点击上方链接立即购买！",
                inline=False
            )
            # 添加提醒
            embed.add_field(
                name="⚠️ 注意",
                value="商品可能很快售罄，请尽快下单",
                inline=False
            )
            # 添加机器人状态
            embed.set_footer(text=f"监控间隔: {config.check_interval}秒 | 持续监控中...")
            
            # 如果有商品图片，添加到通知中
            if product_info.get('image_url'):
                embed.set_image(url=product_info['image_url'])
            
            # 同时发送普通消息以确保通知（可以@用户）
            await channel.send(
                content="@here 🔔 检测到商品可购买！请尽快查看！",
                embed=embed
            )
            logger.info(f"Sent availability notification for {url}")
            
        elif status_change == 'sold_out':
            embed = discord.Embed(
                title="❌ 商品已售罄",
                description=f"检测时间：{current_time}\n\n**商品链接**：\n{url}",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            
            # 如果有商品标题，添加到通知中
            if product_info.get('title'):
                embed.add_field(
                    name="商品名称",
                    value=product_info['title'],
                    inline=False
                )
            
            # 如果有商品图片，添加到通知中
            if product_info.get('image_url'):
                embed.set_image(url=product_info['image_url'])
            
            await channel.send(embed=embed)
            logger.info(f"Sent sold out notification for {url}")

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
                    for url, data in self.store.items.copy().items():
                        available = await self.monitor.monitor_with_delay(url, session)
                        
                        if available is not None:
                            previous_status = data["status"]
                            current_status = "available" if available else "sold_out"
                            
                            if previous_status != current_status:
                                self.store.update_item_status(url, current_status)
                                await self.send_notification(channel, url, current_status)
                
                await asyncio.sleep(config.check_interval)
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {str(e)}")
                await asyncio.sleep(config.check_interval)

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
            
            # 获取商品信息
            async with aiohttp.ClientSession() as session:
                product_info = await self.monitor.get_product_info(url, session)
            
            if self.store.add_item(url):
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
            # 获取商品信息
            async with aiohttp.ClientSession() as session:
                product_info = await self.monitor.get_product_info(url, session)
            
            if self.store.remove_item(url):
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
                
                # 添加商品图片
                if product_info.get('image_url'):
                    embed.set_image(url=product_info['image_url'])
                
                logger.info(f"Removed item from watch: {url}")
            else:
                embed = discord.Embed(
                    title="⚠️ 移除失败",
                    description="该商品不在监控列表中",
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
                
                logger.warning(f"Attempted to remove non-existent item: {url}")
            
            await ctx.send(embed=embed)

        @self.command(name='list')
        async def list_items(ctx):
            """显示所有正在监控的商品"""
            if not self.store.items:
                embed = discord.Embed(
                    title="监控列表",
                    description="目前没有监控任何商品",
                    color=discord.Color.blue()
                )
                await ctx.send(embed=embed)
                return
            
            async with aiohttp.ClientSession() as session:
                for url in self.store.items:
                    # 为每个商品创建单独的embed
                    product_info = await self.monitor.get_product_info(url, session)
                    status = self.store.items[url]["status"]
                    
                    embed = discord.Embed(
                        title="🔍 监控商品",
                        description=f"**商品链接**：\n{url}\n\n**状态**：{'可购买' if status == 'available' else '售罄'}",
                        color=discord.Color.green() if status == 'available' else discord.Color.red()
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
                    
                    await ctx.send(embed=embed)

        @self.command(name='status')
        async def status(ctx):
            """显示机器人状态"""
            embed = discord.Embed(
                title="机器人状态",
                color=discord.Color.blue()
            )
            embed.add_field(name="监控商品数量", value=str(len(self.store.items)), inline=False)
            embed.add_field(name="检查间隔", value=f"{config.check_interval}秒", inline=False)
            embed.add_field(name="运行状态", value="🟢 正常运行中", inline=False)
            
            await ctx.send(embed=embed)

def run_bot():
    """运行Discord机器人"""
    bot = MonitorBot()
    bot.run(config.discord_token) 