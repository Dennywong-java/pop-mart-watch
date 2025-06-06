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
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

logger = logging.getLogger(__name__)

class Monitor:
    """
    商品监控类
    负责检查商品页面的可用性状态
    """
    
    # 监控项目文件路径
    MONITORED_ITEMS_FILE = 'monitored_items.json'
    
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
        try:
            # 配置 Chrome 选项
            options = webdriver.ChromeOptions()
            options.add_argument('--headless')  # 无头模式
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--window-size=1920,1080')
            options.add_argument('--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36')
            
            # 为 M1/M2 Mac 特别配置
            if os.uname().machine == 'arm64':
                options.binary_location = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
            
            # 安装并获取 ChromeDriver，指定特定版本和架构
            driver_manager = ChromeDriverManager()
            if os.uname().machine == 'arm64':
                driver_manager.driver_cache_path = os.path.join(os.path.expanduser('~'), '.wdm', 'drivers', 'chromedriver', 'mac-arm64')
            
            driver_path = driver_manager.install()
            
            # 确保 driver_path 指向正确的可执行文件
            if os.path.isdir(driver_path):
                possible_paths = [
                    os.path.join(driver_path, 'chromedriver'),
                    os.path.join(driver_path, 'chromedriver-mac-arm64', 'chromedriver'),
                    os.path.join(driver_path, 'chromedriver-mac-x64', 'chromedriver')
                ]
                for path in possible_paths:
                    if os.path.isfile(path) and os.access(path, os.X_OK):
                        driver_path = path
                        break
            
            logger.info(f"使用 ChromeDriver 路径: {driver_path}")
            
            # 创建 Service 对象
            service = Service(executable_path=driver_path)
            
            # 创建 WebDriver
            driver = webdriver.Chrome(service=service, options=options)
            return driver
        except Exception as e:
            logger.error(f"创建 WebDriver 失败: {str(e)}")
            return None

    @staticmethod
    async def check_product_availability(url: str, session: aiohttp.ClientSession) -> bool:
        """检查商品是否可购买"""
        try:
            driver = Monitor.create_driver()
            if not driver:
                return None
            
            try:
                # 加载页面
                driver.get(url)
                
                # 等待页面加载完成
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                
                # 记录页面内容以便调试
                logger.debug(f"页面标题: {driver.title}")
                logger.debug(f"页面 URL: {driver.current_url}")
                
                # 检查所有可能的按钮和状态指示器
                elements = driver.find_elements(By.XPATH, "//*[contains(@class, 'button') or self::button or self::a or self::div or self::span or self::p or self::input]")
                
                for element in elements:
                    try:
                        text = element.text.strip()
                        class_name = element.get_attribute("class")
                        disabled = element.get_attribute("disabled")
                        
                        # 记录找到的元素信息
                        if text:
                            logger.debug(f"找到元素: text='{text}', class={class_name}, disabled={disabled}")
                        
                        # 检查可购买状态
                        if any(keyword.lower() in text.lower() for keyword in Monitor.AVAILABLE_KEYWORDS):
                            if not disabled and not ('sold-out' in str(class_name).lower()):
                                logger.info(f"商品可购买: {text}")
                                return True
                        
                        # 检查售罄状态
                        if any(keyword.lower() in text.lower() for keyword in Monitor.SOLD_OUT_KEYWORDS):
                            logger.info(f"商品已售罄: {text}")
                            return False
                    except Exception as e:
                        logger.warning(f"处理元素时出错: {str(e)}")
                        continue
                
                # 检查商品状态的其他指示器
                status_elements = driver.find_elements(By.XPATH, "//*[contains(@class, 'status') or contains(@class, 'stock')]")
                for element in status_elements:
                    try:
                        text = element.text.strip()
                        logger.debug(f"找到状态元素: {text}")
                        
                        if any(keyword.lower() in text.lower() for keyword in Monitor.AVAILABLE_KEYWORDS):
                            logger.info(f"商品可购买（状态元素）: {text}")
                            return True
                        
                        if any(keyword.lower() in text.lower() for keyword in Monitor.SOLD_OUT_KEYWORDS):
                            logger.info(f"商品已售罄（状态元素）: {text}")
                            return False
                    except Exception as e:
                        logger.warning(f"处理状态元素时出错: {str(e)}")
                        continue
                
                # 如果没有找到明确的状态指示器，记录警告
                logger.warning("无法确定商品状态: 未找到相关关键词")
                return None
                
            except TimeoutException:
                logger.error("页面加载超时")
                return None
            except Exception as e:
                logger.error(f"检查商品状态时出错: {str(e)}")
                return None
            finally:
                driver.quit()
                
        except Exception as e:
            logger.error(f"检查商品状态时出错: {str(e)}")
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