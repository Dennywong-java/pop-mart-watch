"""
监控模块，负责检查商品可用性
"""
import os
import logging
import asyncio
from typing import Optional, Dict, List, Tuple
import aiohttp
from bs4 import BeautifulSoup
from src.config import config
import json
import re
from urllib.parse import quote, urlparse, urlunparse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.service import Service
import time
import tempfile
import shutil
import uuid
import platform
import subprocess
from pathlib import Path
import socket
import dns.resolver
from enum import Enum
from datetime import datetime
import traceback

logger = logging.getLogger(__name__)

class ProductStatus(Enum):
    """商品状态枚举"""
    UNKNOWN = "unknown"          # 未知状态（比如请求失败）
    IN_STOCK = "in_stock"        # 有货
    SOLD_OUT = "sold_out"        # 售罄
    COMING_SOON = "coming_soon"  # 即将发售
    OFF_SHELF = "off_shelf"      # 下架

class Monitor:
    """
    商品监控类
    负责检查商品页面的可用性状态
    """
    
    def __init__(self):
        """初始化监控器"""
        self.monitored_items = {}
        self.data_dir = "data"
        self.data_file = os.path.join(self.data_dir, "monitored_items.json")
        self._load_monitored_items()
    
    # 可购买状态的关键词
    AVAILABLE_KEYWORDS = [
        'ADD TO BAG',
        'add to bag',
        'add to cart',
        'buy now',
        'purchase',
        'checkout',
        'in stock',
        'add to shopping bag',
        'add to my bag',
        'Add to Cart',
        'BUY NOW'
    ]
    
    # 售罄状态的关键词
    SOLD_OUT_KEYWORDS = [
        'SOLD OUT',
        'sold out',
        'out of stock',
        'notify me when available',
        'NOTIFY ME WHEN AVAILABLE',
        'currently unavailable',
        'not available',
        'Item Unavailable',
        'item unavailable',
        'Unavailable',
        'Item unavailable'
    ]
    
    # 临时目录列表
    _temp_dirs = []
    
    @classmethod
    def cleanup_temp_dirs(cls):
        """清理所有临时目录"""
        for temp_dir in cls._temp_dirs:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception as e:
                logger.warning(f"清理临时目录失败: {str(e)}")
        cls._temp_dirs.clear()

    def _load_monitored_items(self):
        """从文件加载监控列表"""
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
        
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    self.monitored_items = json.load(f)
                # 兼容旧数据：将字符串状态转换为枚举
                for url, item in self.monitored_items.items():
                    if isinstance(item.get('last_status'), str) or item.get('last_status') is None:
                        item['last_status'] = ProductStatus.UNKNOWN.value
            except Exception as e:
                logger.error(f"加载监控列表失败: {str(e)}")
                self.monitored_items = {}

    def _save_monitored_items(self):
        """保存监控列表到文件"""
        try:
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(self.monitored_items, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存监控列表失败: {str(e)}")

    @staticmethod
    def parse_product_info(url: str) -> Dict[str, str]:
        """从 URL 解析商品信息"""
        # 匹配商品 ID
        match = re.search(r'/products/([^/]+)', url)
        if not match:
            raise ValueError("无效的商品 URL")
        
        product_id = match.group(1)
        
        # 从 URL 中提取商品名称（如果有）
        name_match = re.search(r'/([^/]+)$', url)
        name = name_match.group(1) if name_match else product_id
        
        return {
            'id': product_id,
            'name': name
        }

    async def add_monitored_item(self, url: str, name: str, icon_url: str = None) -> bool:
        """添加商品到监控列表"""
        if url in self.monitored_items:
            return False
        
        self.monitored_items[url] = {
            'name': name,
            'last_status': ProductStatus.UNKNOWN.value,
            'last_check': None,
            'last_notification': None,
            'icon_url': icon_url
        }
        self._save_monitored_items()
        return True

    async def remove_monitored_item(self, url: str) -> bool:
        """从监控列表中移除商品"""
        if url not in self.monitored_items:
            return False
        
        del self.monitored_items[url]
        self._save_monitored_items()
        return True

    @staticmethod
    def create_driver():
        """创建 Chrome WebDriver 实例"""
        temp_dir = None
        try:
            # 创建临时目录
            temp_dir = tempfile.mkdtemp(prefix='chrome_')
            user_data_dir = tempfile.mkdtemp(prefix='chrome_user_')
            Monitor._temp_dirs.extend([temp_dir, user_data_dir])
            
            # 检查并设置 ChromeDriver 路径
            chromedriver_path = None
            try:
                # 首先检查环境变量
                chromedriver_path = os.getenv('CHROMEDRIVER_PATH')
                
                # 如果环境变量未设置，尝试在系统中查找
                if not chromedriver_path:
                    if platform.system() == 'Linux':
                        # 在 Linux 上尝试常见位置
                        possible_paths = [
                            '/usr/local/bin/chromedriver',
                            '/usr/bin/chromedriver',
                            '/snap/bin/chromedriver',
                        ]
                        for path in possible_paths:
                            if os.path.exists(path):
                                chromedriver_path = path
                                break
                        
                        # 如果还是找不到，尝试使用 which 命令
                        if not chromedriver_path:
                            try:
                                chromedriver_path = subprocess.check_output(['which', 'chromedriver']).decode().strip()
                            except:
                                pass
            except Exception as e:
                logger.warning(f"查找 ChromeDriver 路径时出错: {str(e)}")
            
            if not chromedriver_path or not os.path.exists(chromedriver_path):
                logger.error("未找到 ChromeDriver，请确保它已安装并在系统路径中")
                return None
            
            # 配置 Chrome 选项
            options = webdriver.ChromeOptions()
            
            # 设置 Chrome 二进制文件路径
            chrome_binary = os.getenv('CHROME_BINARY', '/usr/bin/google-chrome')
            if os.path.exists(chrome_binary):
                options.binary_location = chrome_binary
            
            # 基本配置
            options.add_argument('--headless=new')  # 使用新的无头模式
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--disable-extensions')
            options.add_argument('--disable-setuid-sandbox')
            options.add_argument('--disable-software-rasterizer')
            
            # 用户数据目录配置
            options.add_argument('--no-first-run')
            options.add_argument('--no-default-browser-check')
            options.add_argument('--password-store=basic')
            options.add_argument('--use-mock-keychain')
            options.add_argument(f'--user-data-dir={user_data_dir}')  # 使用临时目录
            options.add_argument(f'--disk-cache-dir={os.path.join(user_data_dir, "cache")}')
            options.add_argument('--disk-cache-size=1')
            options.add_argument('--media-cache-size=1')
            options.add_argument('--aggressive-cache-discard')
            
            # 网络配置
            options.add_argument('--dns-prefetch-disable')  # 禁用 DNS 预取
            options.add_argument('--no-proxy-server')  # 禁用代理
            options.add_argument('--disable-ipv6')  # 禁用 IPv6
            options.add_argument('--disable-background-networking')  # 禁用后台网络
            options.add_argument('--disable-sync')  # 禁用同步
            options.add_argument('--disable-web-security')  # 禁用网络安全限制
            options.add_argument('--ignore-certificate-errors')  # 忽略证书错误
            options.add_argument('--ignore-ssl-errors')  # 忽略 SSL 错误
            
            # 性能优化
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            
            # 创建 WebDriver
            service = Service(chromedriver_path)
            driver = webdriver.Chrome(service=service, options=options)
            
            return driver
            
        except Exception as e:
            logger.error(f"创建 WebDriver 时出错: {str(e)}")
            if temp_dir:
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except:
                    pass
            return None

    @staticmethod
    def normalize_domain(url):
        """规范化域名"""
        try:
            # 从 URL 中提取域名
            domain = url.split('/')[2].lower()
            
            # 检查是否是 POP MART 域名
            if not any(domain.endswith(d) for d in ['popmart.com', 'pop-mart.com']):
                return None
            
            # 规范化域名
            if domain.startswith('www.'):
                domain = domain[4:]
            
            # 尝试不同的域名变体
            domain_variants = [
                domain,
                domain.replace('popmart.com', 'pop-mart.com'),
                domain.replace('pop-mart.com', 'popmart.com'),
                f'www.{domain}',
            ]
            
            return domain_variants
        except Exception as e:
            logger.error(f"域名规范化失败: {str(e)}")
            return None

    @staticmethod
    def check_dns(url):
        """检查域名解析"""
        try:
            # 获取域名变体
            domain_variants = Monitor.normalize_domain(url)
            if not domain_variants:
                logger.error("无效的域名")
                return False
            
            # 尝试使用不同的 DNS 服务器
            dns_servers = [
                ('8.8.8.8', 'Google DNS'),
                ('1.1.1.1', 'Cloudflare DNS'),
                ('208.67.222.222', 'OpenDNS')
            ]
            
            for domain in domain_variants:
                for dns_ip, dns_name in dns_servers:
                    try:
                        resolver = dns.resolver.Resolver()
                        resolver.nameservers = [dns_ip]
                        answers = resolver.resolve(domain, 'A')
                        logger.info(f"使用 {dns_name} ({dns_ip}) 解析 {domain}: {[str(rdata) for rdata in answers]}")
                        return domain  # 返回成功解析的域名
                    except Exception as e:
                        logger.warning(f"使用 {dns_name} ({dns_ip}) 解析 {domain} 失败: {str(e)}")
            
            # 如果所有 DNS 服务器都失败，尝试使用系统默认 DNS
            for domain in domain_variants:
                try:
                    ip = socket.gethostbyname(domain)
                    logger.info(f"使用系统 DNS 解析 {domain}: {ip}")
                    return domain
                except:
                    continue
            
            logger.error("所有域名变体解析失败")
            return False
        except Exception as e:
            logger.error(f"DNS 解析失败: {str(e)}")
            return False

    @staticmethod
    async def check_network(url):
        """检查网络连接"""
        try:
            # 检查 DNS 解析
            resolved_domain = Monitor.check_dns(url)
            if not resolved_domain:
                return False, url
            
            # 构建新的 URL
            url_parts = url.split('/')
            url_parts[2] = resolved_domain
            new_url = '/'.join(url_parts)
            
            # 尝试 ping
            try:
                result = subprocess.run(['ping', '-c', '1', '-W', '5', resolved_domain], 
                                     capture_output=True, text=True)
                if result.returncode == 0:
                    logger.info(f"Ping {resolved_domain} 成功")
                    return True, new_url
                else:
                    logger.warning(f"Ping {resolved_domain} 失败: {result.stderr}")
            except Exception as e:
                logger.warning(f"Ping 执行失败: {str(e)}")
            
            # 如果 ping 失败，尝试 curl
            try:
                result = subprocess.run(['curl', '-I', '-s', '-m', '10', new_url], 
                                     capture_output=True, text=True)
                if result.returncode == 0:
                    logger.info(f"Curl {new_url} 成功")
                    return True, new_url
                else:
                    logger.warning(f"Curl {new_url} 失败: {result.stderr}")
            except Exception as e:
                logger.warning(f"Curl 执行失败: {str(e)}")
            
            return False, new_url
        except Exception as e:
            logger.error(f"网络检查失败: {str(e)}")
            return False, url

    @staticmethod
    async def check_product_availability(url: str) -> Optional[bool]:
        """检查商品是否可购买"""
        try:
            # 创建 Chrome WebDriver
            driver = Monitor.create_driver()
            if not driver:
                logger.error("无法创建 WebDriver")
                return None
            
            try:
                # 设置页面加载超时
                driver.set_page_load_timeout(30)
                
                # 访问商品页面
                driver.get(url)
                
                # 等待页面加载完成
                WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                
                # 获取页面内容
                page_content = driver.page_source.lower()
                
                # 检查是否可购买
                for keyword in Monitor.AVAILABLE_KEYWORDS:
                    if keyword.lower() in page_content:
                        return True
                
                # 检查是否售罄
                for keyword in Monitor.SOLD_OUT_KEYWORDS:
                    if keyword.lower() in page_content:
                        return False
                
                # 如果没有找到任何关键词，返回 None
                return None
                
            except TimeoutException:
                logger.error(f"页面加载超时: {url}")
                return None
            except WebDriverException as e:
                logger.error(f"WebDriver 错误: {str(e)}")
                return None
            finally:
                try:
                    driver.quit()
                except:
                    pass
                
        except Exception as e:
            logger.error(f"检查商品可用性时出错: {str(e)}")
            return None

    async def check_item_status(self, url: str) -> Tuple[ProductStatus, Optional[str]]:
        """检查商品状态"""
        try:
            # 创建 Chrome WebDriver
            driver = Monitor.create_driver()
            if not driver:
                logger.error("无法创建 WebDriver")
                return ProductStatus.UNKNOWN, None
            
            try:
                # 设置页面加载超时
                driver.set_page_load_timeout(30)
                
                # 访问商品页面
                driver.get(url)
                
                # 等待页面加载完成
                WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                
                # 获取页面内容
                html = driver.page_source
                html_lower = html.lower()
                
                # 记录页面内容用于调试
                content_sample = html[:5000] if len(html) > 5000 else html
                logger.debug(f"商品页面响应内容示例 ({url}):\n{content_sample}")
                
                # 售罄关键词
                sold_out_keywords = ['sold out', 'out of stock', 'currently unavailable']
                for keyword in sold_out_keywords:
                    if keyword in html_lower:
                        logger.info(f"找到售罄关键词: {keyword}")
                        return ProductStatus.SOLD_OUT, None
                
                # 即将发售关键词
                coming_soon_keywords = ['coming soon', 'stay tuned', 'notify me']
                for keyword in coming_soon_keywords:
                    if keyword in html_lower:
                        logger.info(f"找到即将发售关键词: {keyword}")
                        return ProductStatus.COMING_SOON, None
                
                # 可购买关键词
                in_stock_keywords = ['add to cart', 'buy now', 'add to bag', 'purchase']
                for keyword in in_stock_keywords:
                    if keyword in html_lower:
                        logger.info(f"找到可购买关键词: {keyword}")
                        # 尝试提取价格
                        price = None
                        price_patterns = [
                            r'price"[^>]*>([^<]+)',
                            r'price[^>]+>([^<]+)',
                            r'product-price[^>]+>([^<]+)',
                            r'\$\s*\d+\.?\d*'
                        ]
                        for pattern in price_patterns:
                            price_match = re.search(pattern, html)
                            if price_match:
                                price = price_match.group(1) if len(price_match.groups()) > 0 else price_match.group(0)
                                price = price.strip()
                                logger.info(f"找到价格: {price}")
                                break
                        return ProductStatus.IN_STOCK, price
                
                # 检查是否是404页面
                if "404" in html or "page not found" in html_lower:
                    logger.info("页面返回404")
                    return ProductStatus.OFF_SHELF, None
                
                # 如果没有找到任何关键词，记录日志
                logger.warning(f"未找到任何状态关键词 ({url})")
                logger.debug("搜索的关键词：")
                logger.debug(f"售罄关键词: {sold_out_keywords}")
                logger.debug(f"即将发售关键词: {coming_soon_keywords}")
                logger.debug(f"可购买关键词: {in_stock_keywords}")
                
                return ProductStatus.UNKNOWN, None
                
            except TimeoutException:
                logger.error(f"页面加载超时: {url}")
                return ProductStatus.UNKNOWN, None
            except WebDriverException as e:
                logger.error(f"WebDriver 错误: {str(e)}")
                return ProductStatus.UNKNOWN, None
            finally:
                try:
                    driver.quit()
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"检查商品状态时出错 ({url}): {str(e)}")
            logger.error(f"错误类型: {type(e).__name__}")
            logger.error(f"错误详情: {traceback.format_exc()}")
            return ProductStatus.UNKNOWN, None

    async def check_all_items(self) -> list:
        """检查所有商品的状态"""
        notifications = []
        current_time = datetime.now().isoformat()
        
        for url, item in self.monitored_items.items():
            # 获取当前状态
            current_status, price = await self.check_item_status(url)
            previous_status = item.get('last_status', ProductStatus.UNKNOWN.value)
            
            # 记录检查结果
            logger.info(f"商品状态检查 - {item['name']} ({url}):")
            logger.info(f"  当前状态: {current_status.value}")
            logger.info(f"  之前状态: {previous_status}")
            if price:
                logger.info(f"  价格: {price}")
            
            # 状态发生变化时才发送通知
            if current_status.value != previous_status:
                logger.info(f"  状态变化: {previous_status} -> {current_status.value}")
                
                # 更新商品信息
                item.update({
                    'last_status': current_status.value,
                    'last_check': current_time,
                    'last_notification': current_time,
                    'price': price
                })
                
                # 生成通知消息
                status_messages = {
                    ProductStatus.IN_STOCK.value: f"🟢 商品已上架！{f'价格: {price}' if price else ''}",
                    ProductStatus.SOLD_OUT.value: "🔴 商品已售罄",
                    ProductStatus.COMING_SOON.value: "🟡 商品即将发售",
                    ProductStatus.OFF_SHELF.value: "⚫ 商品已下架",
                    ProductStatus.UNKNOWN.value: "❓ 商品状态未知"
                }
                
                notification = {
                    'url': url,
                    'name': item['name'],
                    'status': current_status.value,
                    'message': status_messages.get(current_status.value, "状态未知"),
                    'price': price,
                    'icon_url': item.get('icon_url')
                }
                notifications.append(notification)
            else:
                # 仅更新检查时间
                item['last_check'] = current_time
            
            # 保存更新后的数据
            self._save_monitored_items()
        
        return notifications 