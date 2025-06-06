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
        
        # 注册命令
        self.setup_commands()
        
    def setup_commands(self):
        """设置斜杠命令"""
        @self.tree.command(
            name="watch",
            description="添加商品到监控列表"
        )
        @app_commands.describe(
            url="商品页面的 URL"
        )
        async def watch(interaction: discord.Interaction, url: str):
            try:
                # 验证 URL
                if not any(domain in url for domain in self.config.monitor.allowed_domains):
                    await interaction.response.send_message(
                        f"不支持的域名。允许的域名: {', '.join(self.config.monitor.allowed_domains)}"
                    )
                    return
                
                # 解析商品信息
                try:
                    product_info = Monitor.parse_product_info(url)
                except ValueError as e:
                    await interaction.response.send_message(f"错误: {str(e)}")
                    return
                
                # 添加到监控列表
                success = await self.monitor.add_monitored_item(url, product_info['name'])
                if success:
                    # 构建嵌入消息
                    embed = discord.Embed(
                        title="已添加商品到监控列表",
                        description=product_info['name'],
                        color=discord.Color.green()
                    )
                    embed.add_field(name="商品 ID", value=product_info['id'], inline=True)
                    embed.add_field(name="URL", value=url, inline=False)
                    
                    await interaction.response.send_message(embed=embed)
                    logger.info(f"添加商品到监控列表: {product_info['name']} (ID: {product_info['id']})")
                else:
                    await interaction.response.send_message("添加商品失败，可能已经在监控列表中")
                
            except Exception as e:
                logger.error(f"添加监控商品时出错: {str(e)}")
                await interaction.response.send_message(f"添加监控商品时出错: {str(e)}")
        
        @self.tree.command(
            name="unwatch",
            description="从监控列表中移除商品"
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
            description="显示所有正在监控的商品"
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
                        status = "可购买 ✅" if item.get('last_status') else "已售罄 ❌"
                        embed.add_field(
                            name=f"{item['name']} (ID: {product_info['id']})",
                            value=f"状态: {status}\n{url}",
                            inline=False
                        )
                    except:
                        status = "可购买 ✅" if item.get('last_status') else "已售罄 ❌"
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
            description="显示机器人状态"
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
    
    async def setup_hook(self):
        """设置钩子"""
        logger.info("初始化 Discord 机器人...")
        
        # 同步命令到服务器
        try:
            # 先同步到指定服务器
            await self.tree.sync(guild=discord.Object(id=self.config.discord.guild_id))
            guild_commands = await self.tree.fetch_commands(guild=discord.Object(id=self.config.discord.guild_id))
            logger.info(f"斜杠命令已同步到服务器 {self.config.discord.guild_id}，共 {len(guild_commands)} 个命令")
            
            # 同步全局命令
            await self.tree.sync()
            global_commands = await self.tree.fetch_commands()
            logger.info(f"斜杠命令已全局同步，共 {len(global_commands)} 个命令")
            
            # 输出所有已注册的命令
            logger.info("已注册的命令：")
            for command in guild_commands:
                logger.info(f"[服务器] /{command.name} - {command.description}")
            for command in global_commands:
                logger.info(f"[全局] /{command.name} - {command.description}")
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
    
    async def monitor_products(self):
        """监控商品状态"""
        while True:
            try:
                for url, item in self.monitor.monitored_items.items():
                    try:
                        # 检查商品状态
                        is_available = await self.monitor.check_product_availability_with_delay(
                            url, self.config.monitor.request_delay
                        )
                        
                        # 如果状态改变，发送通知
                        if is_available != item.get('last_status'):
                            item['last_status'] = is_available
                            self.monitor.save_monitored_items()
                            
                            # 获取商品信息
                            try:
                                product_info = Monitor.parse_product_info(url)
                                product_name = f"{item['name']} (ID: {product_info['id']})"
                            except:
                                product_name = item['name']
                            
                            # 构建嵌入消息
                            embed = discord.Embed(
                                title="商品状态更新",
                                description=product_name,
                                color=discord.Color.green() if is_available else discord.Color.red()
                            )
                            embed.add_field(name="状态", value="可购买 ✅" if is_available else "已售罄 ❌", inline=True)
                            embed.add_field(name="URL", value=url, inline=False)
                            
                            await self.send_notification(embed=embed)
                            
                    except Exception as e:
                        logger.error(f"监控商品时出错 {item['name']}: {str(e)}")
                
                # 等待下一次检查
                await asyncio.sleep(self.config.monitor.check_interval)
                
            except Exception as e:
                logger.error(f"监控任务出错: {str(e)}")
                await asyncio.sleep(60)  # 出错后等待一分钟再继续
    
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

async def run_bot(config: Config):
    """运行 Discord 机器人"""
    try:
        bot = DiscordBot(config)
        await bot.start(config.discord.token)
    except Exception as e:
        logger.error(f"运行机器人时出错: {str(e)}")
        raise