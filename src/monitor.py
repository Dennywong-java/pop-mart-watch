"""
监控模块，负责检查商品可用性
"""
import os
import logging
import asyncio
from typing import Optional, Dict, List
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

logger = logging.getLogger(__name__)

class Monitor:
    """
    商品监控类
    负责检查商品页面的可用性状态
    """
    
    def __init__(self):
        """初始化监控器"""
        self.monitored_items = {}
        self.load_monitored_items()
    
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

    def load_monitored_items(self) -> None:
        """从文件加载监控商品列表"""
        try:
            # 确保数据目录存在
            os.makedirs(os.path.dirname(config.storage.data_file), exist_ok=True)
            
            # 如果文件不存在，创建空文件
            if not os.path.exists(config.storage.data_file):
                with open(config.storage.data_file, 'w', encoding='utf-8') as f:
                    json.dump({}, f)
                self.monitored_items = {}
                return
            
            # 读取文件内容
            with open(config.storage.data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                # 如果是空文件或 null
                if not data:
                    self.monitored_items = {}
                    return
                    
                # 如果数据是列表格式，转换为字典格式
                if isinstance(data, list):
                    self.monitored_items = {}
                    for item in data:
                        self.monitored_items[item['url']] = {
                            'name': item['name'],
                            'url': item['url'],
                            'last_status': item.get('last_status')
                        }
                else:
                    self.monitored_items = data
                    
            logger.info(f"已加载 {len(self.monitored_items)} 个监控商品")
        except Exception as e:
            logger.error(f"加载监控商品列表时出错: {str(e)}")
            self.monitored_items = {}

    def save_monitored_items(self) -> bool:
        """保存监控商品列表到文件"""
        try:
            os.makedirs(os.path.dirname(config.storage.data_file), exist_ok=True)
            with open(config.storage.data_file, 'w', encoding='utf-8') as f:
                json.dump(self.monitored_items, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"保存监控商品列表时出错: {str(e)}")
            return False

    async def add_monitored_item(self, url: str, name: str) -> bool:
        """添加监控商品"""
        try:
            if url in self.monitored_items:
                logger.warning(f"商品已在监控列表中: {url}")
                return False
            
            self.monitored_items[url] = {
                'name': name,
                'url': url,
                'last_status': None
            }
            return self.save_monitored_items()
        except Exception as e:
            logger.error(f"添加监控商品时出错: {str(e)}")
            return False

    async def remove_monitored_item(self, url: str) -> bool:
        """移除监控商品"""
        try:
            if url not in self.monitored_items:
                logger.warning(f"商品不在监控列表中: {url}")
                return False
            
            del self.monitored_items[url]
            return self.save_monitored_items()
        except Exception as e:
            logger.error(f"移除监控商品时出错: {str(e)}")
            return False

    @staticmethod
    def parse_product_info(url: str) -> Dict[str, str]:
        """从 URL 中解析商品信息"""
        try:
            # 移除 URL 中的查询参数
            url = url.split('?')[0].strip('/')
            
            # 匹配商品 ID 和名称
            pattern = r'/products/(\d+)/([^/]+)'
            match = re.search(pattern, url)
            if not match:
                raise ValueError("无效的商品 URL 格式")
            
            product_id = match.group(1)
            product_name = match.group(2).replace('-', ' ').strip()
            
            return {
                'id': product_id,
                'name': product_name,
                'url': url
            }
        except Exception as e:
            logger.error(f"解析商品 URL 时出错: {str(e)}")
            raise ValueError("无法从 URL 解析商品信息")

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

    async def check_product_availability_with_delay(self, url: str, delay: int) -> Optional[bool]:
        """带延迟的商品可用性检查"""
        try:
            # 检查商品可用性
            is_available = await self.check_product_availability(url)
            
            # 添加延迟
            await asyncio.sleep(delay)
            
            return is_available
            
        except Exception as e:
            logger.error(f"检查商品可用性时出错: {str(e)}")
            return None 