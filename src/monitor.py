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
            if os.path.exists(config.storage.data_file):
                with open(config.storage.data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
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

    async def get_product_info(self, url: str, session: Optional[aiohttp.ClientSession] = None) -> Dict[str, str]:
        """获取商品信息"""
        try:
            # 解析商品 ID 和名称
            product_info = self.parse_product_url(url)
            if not product_info:
                return {}

            # 检查网络连接
            if not await self.check_network(url):
                logger.warning(f"无法连接到服务器: {url}")
                return product_info

            # 创建或使用现有的会话
            should_close_session = False
            if session is None:
                session = aiohttp.ClientSession()
                should_close_session = True

            try:
                # 尝试从 API 获取商品信息
                api_info = await self._get_product_info_from_api(product_info['id'], session)
                if api_info:
                    product_info.update(api_info)
                    return product_info

                # 如果 API 获取失败，尝试从 HTML 页面获取
                html_info = await self._get_product_info_from_html(url, session)
                if html_info:
                    product_info.update(html_info)

            finally:
                if should_close_session:
                    await session.close()

            return product_info

        except Exception as e:
            logger.error(f"获取商品信息时出错: {str(e)}")
            return {}

    async def _get_product_info_from_api(self, product_id: str, session: aiohttp.ClientSession) -> Dict[str, str]:
        """从 API 获取商品信息"""
        api_urls = [
            f"https://us.popmart.com/api/v2/products/{product_id}",
            f"https://shop.popmart.com/api/v2/products/{product_id}"
        ]

        for api_url in api_urls:
            try:
                async with session.get(api_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            'title': data.get('title'),
                            'image_url': data.get('image', {}).get('src'),
                            'available': data.get('available', False)
                        }
                    else:
                        logger.warning(f"从 API 获取商品信息失败: {api_url}, 状态码: {response.status}")
            except Exception as e:
                logger.warning(f"从 API 获取商品信息出错: {api_url}, {str(e)}")

        return {}

    async def _get_product_info_from_html(self, url: str, session: aiohttp.ClientSession) -> Dict[str, str]:
        """从 HTML 页面获取商品信息"""
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')

                    # 尝试获取商品标题
                    title = None
                    title_elem = soup.find('h1', {'class': 'product-title'})
                    if title_elem:
                        title = title_elem.text.strip()

                    # 尝试获取商品图片
                    image_url = None
                    image_elem = soup.find('img', {'class': 'product-image'})
                    if image_elem:
                        image_url = image_elem.get('src')

                    # 检查商品状态
                    available = False
                    for keyword in self.AVAILABLE_KEYWORDS:
                        if keyword.lower() in html.lower():
                            available = True
                            break

                    if not available:
                        for keyword in self.SOLD_OUT_KEYWORDS:
                            if keyword.lower() in html.lower():
                                available = False
                                break

                    return {
                        'title': title,
                        'image_url': image_url,
                        'available': available
                    }
                else:
                    logger.warning(f"从 HTML 获取商品信息失败: {url}, 状态码: {response.status}")

        except Exception as e:
            logger.warning(f"从 HTML 获取商品信息出错: {url}, {str(e)}")

        return {} 