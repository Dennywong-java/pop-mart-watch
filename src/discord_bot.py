"""
Discord 机器人模块，处理 Discord 相关功能
"""
import asyncio
import logging
import traceback
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import tasks
import aiohttp
from typing import Optional, Dict, List, Any
from urllib.parse import urlparse
import json
import os

from src.config import Config
from src.monitor import Monitor, ProductStatus

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
        
        # 注册命令
        self.setup_commands()
        
    @staticmethod
    def is_valid_image_url(url: str) -> bool:
        """验证图片 URL 格式是否合法"""
        if not url:
            return False
            
        # 支持的图片格式
        valid_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')
        
        # 检查 URL 是否以支持的图片格式结尾（不区分大小写）
        return url.lower().endswith(valid_extensions)

    def setup_commands(self):
        """设置斜杠命令"""
        # 清除现有命令
        self.tree.clear_commands(guild=discord.Object(id=self.config.discord.guild_id))
        
        @self.tree.command(
            name="watch",
            description="添加商品到监控列表",
            guild=discord.Object(id=self.config.discord.guild_id)  # 将命令注册到特定服务器
        )
        @app_commands.describe(
            url="商品页面的 URL",
            icon_url="商品图片的 URL（可选，支持 jpg/jpeg/png/gif/webp）"
        )
        async def watch(interaction: discord.Interaction, url: str, icon_url: str = None):
            try:
                # 验证 URL
                if not any(domain in url for domain in self.config.monitor.allowed_domains):
                    await interaction.response.send_message(
                        f"不支持的域名。允许的域名: {', '.join(self.config.monitor.allowed_domains)}"
                    )
                    return
                
                # 验证图片 URL（如果提供）
                if icon_url and not self.is_valid_image_url(icon_url):
                    await interaction.response.send_message(
                        "不支持的图片格式。支持的格式：jpg、jpeg、png、gif、webp"
                    )
                    return
                
                # 解析商品信息
                try:
                    product_info = Monitor.parse_product_info(url)
                except ValueError as e:
                    await interaction.response.send_message(f"错误: {str(e)}")
                    return
                
                # 添加到监控列表
                success = await self.monitor.add_monitored_item(url, product_info['name'], icon_url)
                if success:
                    # 构建嵌入消息
                    embed = discord.Embed(
                        title="已添加商品到监控列表",
                        description=product_info['name'],
                        color=discord.Color.green()
                    )
                    embed.add_field(name="商品 ID", value=product_info['id'], inline=True)
                    embed.add_field(name="URL", value=url, inline=False)
                    
                    # 设置图片
                    if icon_url:
                        try:
                            embed.set_thumbnail(url=icon_url)
                            logger.info(f"成功设置商品图片: {icon_url}")
                        except Exception as e:
                            logger.warning(f"设置商品图片失败: {str(e)}")
                    
                    await interaction.response.send_message(embed=embed)
                    logger.info(f"添加商品到监控列表: {product_info['name']} (ID: {product_info['id']})")
                else:
                    await interaction.response.send_message("添加商品失败，可能已经在监控列表中")
                
            except Exception as e:
                logger.error(f"添加监控商品时出错: {str(e)}")
                await interaction.response.send_message(f"添加监控商品时出错: {str(e)}")
        
        @self.tree.command(
            name="unwatch",
            description="从监控列表中移除商品",
            guild=discord.Object(id=self.config.discord.guild_id)  # 将命令注册到特定服务器
        )
        @app_commands.describe(
            url="要移除的商品 URL"
        )
        async def unwatch(interaction: discord.Interaction, url: str):
            try:
                success = await self.monitor.remove_monitored_item(url)
                if success:
                    await interaction.response.send_message(f"已从监控列表移除商品")
                    logger.info(f"从监控列表移除商品: {url}")
                else:
                    await interaction.response.send_message("该商品不在监控列表中")
            except Exception as e:
                logger.error(f"移除监控商品时出错: {str(e)}")
                await interaction.response.send_message(f"移除监控商品时出错: {str(e)}")
        
        @self.tree.command(
            name="list",
            description="显示所有正在监控的商品",
            guild=discord.Object(id=self.config.discord.guild_id)  # 将命令注册到特定服务器
        )
        async def list_items(interaction: discord.Interaction):
            try:
                await interaction.response.defer()
                
                if not self.monitor.monitored_items:
                    await interaction.followup.send("监控列表为空")
                    return
                
                # 构建嵌入消息
                embed = discord.Embed(
                    title="正在监控的商品",
                    description=f"共 {len(self.monitor.monitored_items)} 个商品",
                    color=discord.Color.blue()
                )
                
                # 添加每个商品的信息
                for url, item in self.monitor.monitored_items.items():
                    try:
                        product_info = Monitor.parse_product_info(url)
                        status = "可购买 ✅" if item.get('last_status') == "in_stock" else "已售罄 ❌"
                        embed.add_field(
                            name=f"{item['name']} (ID: {product_info['id']})",
                            value=f"状态: {status}\n{url}",
                            inline=False
                        )
                        
                        # 设置图片（使用第一个商品的图片作为消息的缩略图）
                        if item.get('icon_url') and not embed.thumbnail:
                            embed.set_thumbnail(url=item['icon_url'])
                            
                    except:
                        status = "可购买 ✅" if item.get('last_status') == "in_stock" else "已售罄 ❌"
                        embed.add_field(
                            name=item['name'],
                            value=f"状态: {status}\n{url}",
                            inline=False
                        )
                
                await interaction.followup.send(embed=embed)
                
            except Exception as e:
                logger.error(f"显示监控列表时出错: {str(e)}")
                await interaction.followup.send(f"显示监控列表时出错: {str(e)}")
        
        @self.tree.command(
            name="status",
            description="显示机器人状态",
            guild=discord.Object(id=self.config.discord.guild_id)  # 将命令注册到特定服务器
        )
        async def status(interaction: discord.Interaction):
            try:
                await interaction.response.send_message(
                    f"机器人状态: 正常运行中\n"
                    f"监控商品数量: {len(self.monitor.monitored_items)}\n"
                    f"检查间隔: {self.config.monitor.check_interval} 秒"
                )
            except Exception as e:
                logger.error(f"显示状态时出错: {str(e)}")
                await interaction.response.send_message(f"显示状态时出错: {str(e)}")
                
        logger.info("命令设置完成")
    
    async def setup_hook(self):
        """设置钩子"""
        logger.info("初始化 Discord 机器人...")
        
        # 同步命令到服务器
        try:
            logger.info(f"开始同步命令到服务器 {self.config.discord.guild_id}")
            
            # 同步命令到指定服务器
            logger.info("同步命令到指定服务器...")
            await self.tree.sync(guild=discord.Object(id=self.config.discord.guild_id))
            guild_commands = await self.tree.fetch_commands(guild=discord.Object(id=self.config.discord.guild_id))
            logger.info(f"服务器命令同步完成，共 {len(guild_commands)} 个命令")
            
            # 同步全局命令
            logger.info("同步全局命令...")
            await self.tree.sync()
            global_commands = await self.tree.fetch_commands()
            logger.info(f"全局命令同步完成，共 {len(global_commands)} 个命令")
            
            # 输出所有已注册的命令
            logger.info("已注册的命令：")
            if guild_commands:
                for command in guild_commands:
                    logger.info(f"[服务器] /{command.name} - {command.description}")
            else:
                logger.warning("服务器中没有注册的命令")
                
            if global_commands:
                for command in global_commands:
                    logger.info(f"[全局] /{command.name} - {command.description}")
            else:
                logger.warning("没有注册的全局命令")
                
        except discord.errors.Forbidden as e:
            logger.error(f"权限错误: {str(e)}")
            logger.error("请确保机器人有 applications.commands 权限")
            return
        except discord.errors.HTTPException as e:
            logger.error(f"HTTP 错误: {str(e)}")
            logger.error("可能是 Discord API 限制或网络问题")
            return
        except Exception as e:
            logger.error(f"同步命令时出错: {str(e)}")
            logger.error(f"错误类型: {type(e).__name__}")
            logger.error(f"错误详情: {traceback.format_exc()}")
            return
        
        logger.info("机器人设置完成")
    
    async def on_ready(self):
        """机器人就绪事件处理"""
        logger.info(f"机器人已登录: {self.user.name}")
        
        # 启动监控任务
        self.monitor_task = self.loop.create_task(self.monitor_products())
        logger.info("商品监控任务已启动")
    
    async def monitor_products(self):
        """监控商品状态变化并发送通知"""
        while True:
            try:
                notifications = await self.monitor.check_all_items()
                
                for notification in notifications:
                    # 生成通知消息
                    status_messages = {
                        ProductStatus.IN_STOCK: f"🟢 商品已上架！{f'价格: {notification.price}' if notification.price else ''}",
                        ProductStatus.SOLD_OUT: "🔴 商品已售罄",
                        ProductStatus.COMING_SOON: "🟡 商品即将发售",
                        ProductStatus.OFF_SHELF: "⚫ 商品已下架",
                        ProductStatus.UNKNOWN: "❓ 商品状态未知"
                    }
                    
                    # 获取商品名称
                    product_name = notification.url.split('/')[-1].replace('-', ' ')
                    
                    # 创建嵌入消息
                    embed = discord.Embed(
                        title=f"商品状态更新: {product_name}",
                        description=status_messages.get(notification.new_status, "状态未知"),
                        url=notification.url,
                        color=discord.Color.green() if notification.new_status == ProductStatus.IN_STOCK else discord.Color.red()
                    )
                    
                    # 添加状态变化信息
                    embed.add_field(
                        name="状态变化",
                        value=f"{notification.old_status.value} → {notification.new_status.value}",
                        inline=False
                    )
                    
                    # 如果有价格，添加价格信息
                    if notification.price:
                        embed.add_field(name="价格", value=notification.price, inline=True)
                    
                    # 添加时间戳
                    embed.timestamp = datetime.now()
                    
                    # 发送通知
                    for channel_id in self.notification_channels:
                        try:
                            channel = self.get_channel(channel_id)
                            if channel:
                                await channel.send(embed=embed)
                            else:
                                logger.warning(f"找不到频道: {channel_id}")
                        except Exception as e:
                            logger.error(f"发送通知到频道 {channel_id} 时出错: {str(e)}")
                
            except Exception as e:
                logger.error(f"监控任务出错: {str(e)}")
                logger.error(traceback.format_exc())
            
            # 等待下一次检查
            try:
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                logger.info("监控任务被取消")
                break
            except Exception as e:
                logger.error(f"等待间隔时出错: {str(e)}")
                await asyncio.sleep(60)  # 发生错误时使用较长的等待时间
    
    async def send_notification(self, embed: discord.Embed):
        """发送通知消息到指定频道"""
        try:
            channel = self.get_channel(self.config.discord.channel_id)
            if channel:
                await channel.send(embed=embed)
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

    async def check_and_notify(self):
        """检查商品状态并发送通知"""
        try:
            notifications = await self.monitor.check_all_items()
            
            if notifications:
                channel = self.get_channel(self.config.discord.channel_id)
                if channel:
                    for notification in notifications:
                        embed = discord.Embed(
                            title=notification['name'],
                            url=notification['url'],
                            description=notification['message'],
                            color=self._get_status_color(notification['status'])
                        )
                        
                        if notification.get('price'):
                            embed.add_field(name="价格", value=notification['price'], inline=True)
                            
                        await channel.send(embed=embed)
                else:
                    logger.error(f"找不到通知频道: {self.config.discord.channel_id}")
                    
        except Exception as e:
            logger.error(f"检查商品状态时出错: {str(e)}")
            
    def _get_status_color(self, status: str) -> discord.Color:
        """获取状态对应的颜色"""
        status_colors = {
            'in_stock': discord.Color.green(),
            'sold_out': discord.Color.red(),
            'coming_soon': discord.Color.gold(),
            'off_shelf': discord.Color.dark_gray(),
            'unknown': discord.Color.light_gray()
        }
        return status_colors.get(status, discord.Color.default())

async def run_bot(config: Config):
    """运行 Discord 机器人"""
    try:
        bot = DiscordBot(config)
        await bot.start(config.discord.token)
    except Exception as e:
        logger.error(f"运行机器人时出错: {str(e)}")
        raise