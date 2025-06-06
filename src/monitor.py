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
            Monitor._temp_dirs.append(temp_dir)
            
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
            options.add_argument(f'--user-data-dir=/dev/null')  # 完全禁用用户数据目录
            options.add_argument('--disk-cache-dir=/dev/null')  # 禁用磁盘缓存
            options.add_argument('--disk-cache-size=1')  # 最小化磁盘缓存
            options.add_argument('--media-cache-size=1')  # 最小化媒体缓存
            options.add_argument('--aggressive-cache-discard')  # 激进的缓存清理
            
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
            options.add_argument('--disable-web-security')
            options.add_argument('--disable-databases')
            
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
                    
                    service = Service()
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
            if temp_dir and temp_dir in Monitor._temp_dirs:
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    Monitor._temp_dirs.remove(temp_dir)
                except:
                    pass

    @staticmethod
    async def check_product_availability(url: str, session: aiohttp.ClientSession) -> Optional[bool]:
        """检查商品是否可购买"""
        driver = None
        try:
            # 正确处理URL编码
            url_parts = url.split('/')
            product_name = url_parts[-1]
            product_id = url_parts[-2]
            encoded_name = quote(product_name, safe='')
            fixed_url = f"{'/'.join(url_parts[:-1])}/{encoded_name}"
            
            driver = Monitor.create_driver()
            if not driver:
                logger.error("无法创建 WebDriver")
                return None
            
            try:
                logger.debug(f"访问商品页面: {fixed_url}")
                driver.get(fixed_url)
                
                # 等待页面加载
                try:
                    WebDriverWait(driver, 20).until(
                        EC.presence_of_element_located((By.TAG_NAME, "body"))
                    )
                except TimeoutException:
                    logger.warning("页面加载超时")
                    return None
                
                # 获取页面标题和URL用于调试
                try:
                    title = driver.title
                    current_url = driver.current_url
                    logger.debug(f"页面标题: {title}")
                    logger.debug(f"页面 URL: {current_url}")
                except:
                    logger.warning("无法获取页面标题或URL")
                
                # 如果页面返回400，尝试使用备用域名
                if "400 Bad Request" in driver.page_source:
                    alternate_url = fixed_url.replace("popmart.com", "pop-mart.com")
                    logger.debug(f"尝试备用域名: {alternate_url}")
                    driver.get(alternate_url)
                    try:
                        WebDriverWait(driver, 20).until(
                            EC.presence_of_element_located((By.TAG_NAME, "body"))
                        )
                    except TimeoutException:
                        logger.warning("备用域名页面加载超时")
                        return None
                
                # 查找可购买状态相关元素
                buttons = driver.find_elements(By.XPATH, 
                    "//*[contains(@class, 'button') or self::button or self::a or self::div or self::span or self::p or self::h1 or self::h2 or self::h3 or self::h4 or self::h5 or self::h6]"
                )
                
                # 查找库存状态相关元素
                status_elements = driver.find_elements(By.XPATH,
                    "//*[contains(@class, 'status') or contains(@class, 'stock')]"
                )
                
                # 检查所有文本内容
                all_texts = []
                for element in buttons + status_elements:
                    try:
                        text = element.text.strip()
                        if text:
                            all_texts.append(text.upper())
                    except:
                        continue
                
                # 如果找不到任何相关元素，返回None
                if not all_texts:
                    logger.warning("无法确定商品状态: 未找到相关关键词")
                    return None
                
                # 检查是否可购买
                for text in all_texts:
                    if any(keyword.upper() in text for keyword in Monitor.AVAILABLE_KEYWORDS):
                        return True
                    if any(keyword.upper() in text for keyword in Monitor.SOLD_OUT_KEYWORDS):
                        return False
                
                logger.warning(f"无法确定商品状态: 找到的文本 - {', '.join(all_texts)}")
                return None
                
            finally:
                if driver:
                    try:
                        driver.quit()
                    except:
                        pass
                
        except Exception as e:
            logger.error(f"检查商品可用性时出错: {str(e)}")
            if driver:
                try:
                    driver.quit()
                except:
                    pass
            return None

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