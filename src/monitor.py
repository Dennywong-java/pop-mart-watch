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
from urllib.parse import quote
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
    
    # 监控项目文件路径
    MONITORED_ITEMS_FILE = 'monitored_items.json'
    
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

    @staticmethod
    def parse_product_url(url: str) -> Dict[str, str]:
        """从URL中解析产品信息"""
        try:
            pattern = r'/products/(\d+)/([^/]+)'
            match = re.search(pattern, url)
            if match:
                product_id = match.group(1)
                product_name = match.group(2).replace('-', ' ').title()
                return {
                    'id': product_id,
                    'name': product_name,
                    'url': url
                }
        except Exception as e:
            logger.error(f"解析产品URL时出错: {e}")
        return {}

    @staticmethod
    def load_monitored_items() -> List[Dict[str, str]]:
        """加载监控项目列表"""
        try:
            if os.path.exists(Monitor.MONITORED_ITEMS_FILE):
                with open(Monitor.MONITORED_ITEMS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return []
        except Exception as e:
            logger.error(f"Error loading monitored items: {str(e)}")
            return []

    @staticmethod
    def save_monitored_items(items: List[Dict[str, str]]) -> bool:
        """保存监控项目列表"""
        try:
            with open(Monitor.MONITORED_ITEMS_FILE, 'w', encoding='utf-8') as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"Error saving monitored items: {str(e)}")
            return False

    @staticmethod
    async def add_monitored_item(url: str) -> bool:
        """添加监控项目"""
        try:
            product_info = Monitor.parse_product_url(url)
            if not product_info:
                logger.error(f"Invalid product URL: {url}")
                return False
            
            items = Monitor.load_monitored_items()
            if any(item['id'] == product_info['id'] for item in items):
                logger.warning(f"Product {product_info['id']} already monitored")
                return False
            
            items.append(product_info)
            return Monitor.save_monitored_items(items)
        except Exception as e:
            logger.error(f"Error adding monitored item: {str(e)}")
            return False

    @staticmethod
    async def remove_monitored_item(url: str) -> bool:
        """移除监控项目"""
        try:
            product_info = Monitor.parse_product_url(url)
            if not product_info:
                logger.error(f"Invalid product URL: {url}")
                return False
            
            items = Monitor.load_monitored_items()
            original_length = len(items)
            items = [item for item in items if item['id'] != product_info['id']]
            
            if len(items) == original_length:
                logger.warning(f"Product {product_info['id']} not found in monitored items")
                return False
            
            return Monitor.save_monitored_items(items)
        except Exception as e:
            logger.error(f"Error removing monitored item: {str(e)}")
            return False

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
            options.add_argument('--disable-software-rasterizer')
            options.add_argument('--disable-gpu-sandbox')
            options.add_argument('--disable-gpu-compositing')
            options.add_argument('--disable-gpu-program-cache')
            options.add_argument('--disable-gpu-watchdog')
            options.add_argument('--disable-webgl')
            options.add_argument('--disable-webgl2')
            options.add_argument('--disable-gl-extensions')
            
            # 禁用不必要的功能
            options.add_argument('--disable-logging')
            options.add_argument('--disable-in-process-stack-traces')
            options.add_argument('--disable-login-animations')
            options.add_argument('--disable-modal-animations')
            options.add_argument('--disable-reading-from-canvas')
            options.add_argument('--disable-site-isolation-trials')
            options.add_argument('--disable-smooth-scrolling')
            options.add_argument('--disable-speech-api')
            
            # 设置页面加载策略
            options.page_load_strategy = 'eager'
            
            # 设置超时时间
            options.set_capability('pageLoadStrategy', 'eager')
            options.set_capability('unhandledPromptBehavior', 'accept')
            
            # 禁用图片和其他媒体加载
            prefs = {
                'profile.managed_default_content_settings.images': 2,
                'profile.managed_default_content_settings.media_stream': 2,
                'profile.managed_default_content_settings.plugins': 2,
                'profile.default_content_settings.popups': 2,
                'profile.managed_default_content_settings.notifications': 2,
                'profile.managed_default_content_settings.automatic_downloads': 2,
                'profile.managed_default_content_settings.cookies': 2,
                'profile.managed_default_content_settings.javascript': 1,
                'profile.managed_default_content_settings.geolocation': 2,
                'profile.default_content_setting_values.notifications': 2,
                'profile.default_content_setting_values.media_stream_mic': 2,
                'profile.default_content_setting_values.media_stream_camera': 2,
                'profile.default_content_setting_values.geolocation': 2,
                'profile.default_content_setting_values.cookies': 2,
                'download.default_directory': temp_dir,
                'download.prompt_for_download': False,
                'download.directory_upgrade': True,
                'safebrowsing.enabled': False,
                'credentials_enable_service': False,
                'password_manager_enabled': False,
                'webrtc.ip_handling_policy': 'disable_non_proxied_udp',
                'webrtc.multiple_routes_enabled': False,
                'webrtc.nonproxied_udp_enabled': False
            }
            options.add_experimental_option('prefs', prefs)
            
            # 禁用开发者工具和自动化提示
            options.add_experimental_option('excludeSwitches', [
                'enable-automation',
                'enable-logging',
                'enable-blink-features',
                'ignore-certificate-errors',
                'safebrowsing-disable-download-protection',
                'safebrowsing-disable-auto-update',
                'disable-client-side-phishing-detection'
            ])
            
            # 创建 WebDriver
            max_retries = 3
            retry_delay = 2
            last_error = None
            
            for attempt in range(max_retries):
                try:
                    # 在每次尝试前清理可能存在的 Chrome 进程
                    try:
                        os.system('pkill -f chrome')
                        time.sleep(1)  # 等待进程完全终止
                    except:
                        pass
                    
                    service = Service(executable_path=chromedriver_path)
                    
                    # 只在 Windows 平台设置 creation_flags
                    if platform.system() == 'Windows':
                        service.creation_flags = 0x08000000  # 禁用窗口
                    
                    driver = webdriver.Chrome(service=service, options=options)
                    driver.set_page_load_timeout(30)
                    driver.set_script_timeout(30)
                    
                    # 验证 WebDriver 是否正常工作
                    driver.execute_script('return navigator.userAgent')
                    
                    return driver
                except Exception as e:
                    last_error = e
                    logger.warning(f"创建 WebDriver 失败 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
                    try:
                        if 'driver' in locals():
                            driver.quit()
                    except:
                        pass
                    
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        retry_delay *= 2
            
            logger.error(f"创建 WebDriver 失败，已达到最大重试次数: {str(last_error)}")
            return None
            
        except Exception as e:
            logger.error(f"创建 WebDriver 时出错: {str(e)}")
            return None
        finally:
            # 清理所有临时目录
            for dir_path in Monitor._temp_dirs[:]:  # 使用切片创建副本以避免在迭代时修改列表
                try:
                    if os.path.exists(dir_path):
                        shutil.rmtree(dir_path, ignore_errors=True)
                    Monitor._temp_dirs.remove(dir_path)
                except Exception as e:
                    logger.warning(f"清理临时目录失败 {dir_path}: {str(e)}")

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
    def check_network(url):
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
    async def check_product_availability(url, session):
        """检查商品是否可购买"""
        try:
            # 首先检查网络连接
            network_ok, resolved_url = Monitor.check_network(url)
            if not network_ok:
                logger.error("网络连接检查失败")
                return False
            
            driver = None
            try:
                driver = Monitor.create_driver()
                if not driver:
                    logger.error("无法创建 WebDriver")
                    return False

                # 设置页面加载超时
                driver.set_page_load_timeout(30)
                driver.set_script_timeout(30)

                # 添加重试机制
                max_retries = 3
                retry_delay = 2

                for attempt in range(max_retries):
                    try:
                        # 清除所有 cookies
                        driver.delete_all_cookies()
                        
                        # 获取域名
                        main_domain = resolved_url.split('/')[2]
                        
                        # 设置自定义 DNS
                        driver.execute_cdp_cmd('Network.setDNSClientResolver', {
                            'nameservers': ['8.8.8.8', '1.1.1.1']
                        })
                        
                        # 先访问主域名以建立连接
                        driver.get(f'https://{main_domain}')
                        
                        # 等待一下以确保连接建立
                        time.sleep(2)
                        
                        # 然后访问实际的 URL
                        driver.get(resolved_url)
                        
                        # 等待页面加载完成
                        WebDriverWait(driver, 30).until(
                            lambda d: d.execute_script('return document.readyState') == 'complete'
                        )
                        
                        # 检查是否有购买按钮
                        buy_button = driver.find_element(By.CSS_SELECTOR, '[data-testid="AddToCartButton"]')
                        return not ('disabled' in buy_button.get_attribute('class').lower() or 
                                  'sold' in buy_button.get_attribute('class').lower())
                        
                    except Exception as e:
                        if 'net::ERR_NAME_NOT_RESOLVED' in str(e):
                            logger.warning(f"DNS 解析失败 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
                        else:
                            logger.warning(f"检查商品可用性时出错 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
                        
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay)
                            retry_delay *= 2
                            continue
                        else:
                            logger.error(f"检查商品可用性失败，已达到最大重试次数: {str(e)}")
                            return False

            except Exception as e:
                logger.error(f"检查商品可用性时出错: {str(e)}")
                return False
                
            finally:
                try:
                    if driver:
                        driver.quit()
                except:
                    pass

            return False
            
        except Exception as e:
            logger.error(f"检查商品可用性时出错: {str(e)}")
            return False

    @staticmethod
    async def check_product_availability_with_delay(url: str, session: aiohttp.ClientSession) -> Optional[bool]:
        """带延迟的商品监控"""
        try:
            await asyncio.sleep(config.request_delay)
            return await Monitor.check_product_availability(url, session)
        except Exception as e:
            logger.error(f"检查商品状态时出错: {str(e)}")
            return None

    async def get_product_info(self, url: str, session: Optional[aiohttp.ClientSession] = None) -> Dict[str, str]:
        """获取商品信息
        
        Args:
            url: 商品URL
            session: 可选的aiohttp会话
            
        Returns:
            包含商品信息的字典
        """
        product_info = self.parse_product_url(url)
        if not product_info:
            return {}
            
        try:
            if session is None:
                async with aiohttp.ClientSession() as new_session:
                    async with new_session.get(url) as response:
                        if response.status == 200:
                            html = await response.text()
                            soup = BeautifulSoup(html, 'html.parser')
                            title = soup.title.string if soup.title else product_info['name']
                            product_info['title'] = title
            else:
                async with session.get(url) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        title = soup.title.string if soup.title else product_info['name']
                        product_info['title'] = title
                        
            return product_info
        except Exception as e:
            logger.error(f"获取商品信息时出错: {e}")
            return product_info  # 返回基本信息 