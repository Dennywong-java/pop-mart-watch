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
from dataclasses import dataclass

logger = logging.getLogger(__name__)

class ProductStatus(Enum):
    """商品状态枚举"""
    UNKNOWN = "unknown"          # 未知状态（比如请求失败）
    IN_STOCK = "in_stock"        # 有货
    SOLD_OUT = "sold_out"        # 售罄
    COMING_SOON = "coming_soon"  # 即将发售
    OFF_SHELF = "off_shelf"      # 下架

@dataclass
class Notification:
    """状态变化通知"""
    url: str                    # 商品URL
    old_status: ProductStatus   # 之前的状态
    new_status: ProductStatus   # 新状态
    price: Optional[str] = None # 价格（可选）

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
        'add to my bag',
        'ADD TO MY BAG',
        'BUY NOW',
    ]
    
    # 售罄状态的关键词
    SOLD_OUT_KEYWORDS = [
        'NOTIFY ME WHEN AVAILABLE',
    ]
    
    # 即将发售关键词
    COMING_SOON_KEYWORDS = [
        'coming soon',
        'stay tuned',
        'notify me'
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
    def create_driver() -> Optional[webdriver.Chrome]:
        """创建Chrome WebDriver实例"""
        try:
            chrome_options = webdriver.ChromeOptions()
            chrome_options.add_argument('--headless')  # 无界面模式
            chrome_options.add_argument('--no-sandbox')  # 禁用沙盒
            chrome_options.add_argument('--disable-dev-shm-usage')  # 禁用/dev/shm使用
            chrome_options.add_argument('--disable-gpu')  # 禁用GPU加速
            chrome_options.add_argument('--disable-software-rasterizer')  # 禁用软件光栅化
            chrome_options.add_argument('--disable-extensions')  # 禁用扩展
            chrome_options.add_argument('--disable-infobars')  # 禁用信息栏
            chrome_options.add_argument('--disable-notifications')  # 禁用通知
            chrome_options.add_argument('--disable-popup-blocking')  # 禁用弹出窗口阻止
            chrome_options.add_argument('--ignore-certificate-errors')  # 忽略证书错误
            chrome_options.add_argument('--log-level=3')  # 只显示致命错误
            chrome_options.add_argument('--silent')  # 静默模式
            chrome_options.add_argument('--disable-blink-features=AutomationControlled')  # 禁用自动化控制检测
            chrome_options.add_argument('--disable-web-security')  # 禁用网页安全性检查
            
            # 添加性能优化选项
            chrome_options.add_argument('--disable-features=NetworkService')
            chrome_options.add_argument('--disable-features=VizDisplayCompositor')
            chrome_options.add_argument('--disable-accelerated-2d-canvas')
            chrome_options.add_argument('--disable-accelerated-jpeg-decoding')
            chrome_options.add_argument('--disable-accelerated-mjpeg-decode')
            chrome_options.add_argument('--disable-accelerated-video-decode')
            
            # 设置页面加载策略
            chrome_options.page_load_strategy = 'eager'  # 等待 DOMContentLoaded 事件
            
            # 添加实验性选项
            chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            
            # 设置窗口大小
            chrome_options.add_argument('--window-size=1920,1080')
            
            # 创建服务对象
            service = Service()
            service.start()
            
            # 创建WebDriver实例
            driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # 设置脚本和页面加载超时
            driver.set_script_timeout(5)
            driver.set_page_load_timeout(10)
            
            # 验证driver是否正常工作
            try:
                driver.execute_script('return navigator.userAgent')
            except Exception as e:
                logger.error(f"Driver验证失败: {str(e)}")
                driver.quit()
                return None
                
            return driver
            
        except Exception as e:
            logger.error(f"创建WebDriver时出错: {str(e)}")
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
        driver = None
        max_retries = 2  # 最大重试次数
        retry_count = 0
        
        while retry_count <= max_retries:
            try:
                # 创建 Chrome WebDriver
                driver = Monitor.create_driver()
                if not driver:
                    logger.error("无法创建 WebDriver")
                    return ProductStatus.UNKNOWN, None
                
                try:
                    # 设置更短的页面加载超时
                    driver.set_page_load_timeout(10)  # 进一步减少到10秒
                    driver.set_script_timeout(5)      # 减少脚本超时
                    
                    # 访问商品页面
                    driver.get(url)
                    
                    # 使用更短的等待时间和更快的检查方式
                    try:
                        # 等待 body 元素出现，使用更短的超时时间
                        WebDriverWait(driver, 5).until(
                            EC.presence_of_element_located((By.TAG_NAME, "body"))
                        )
                        
                        # 使用JavaScript检查页面加载状态，带有超时控制
                        async def wait_for_page_load():
                            try:
                                async def check_ready_state():
                                    for _ in range(10):  # 最多尝试10次
                                        try:
                                            ready_state = driver.execute_script("return document.readyState")
                                            if ready_state == "complete":
                                                return True
                                            await asyncio.sleep(0.3)  # 减少检查间隔
                                        except Exception:
                                            break
                                    return False
                                
                                # 使用更短的超时时间
                                await asyncio.wait_for(check_ready_state(), timeout=5)
                            except asyncio.TimeoutError:
                                logger.warning("等待页面加载完成超时")
                            except Exception as e:
                                logger.warning(f"等待页面加载时出错: {str(e)}")
                        
                        await wait_for_page_load()
                        
                    except TimeoutException:
                        logger.warning("等待页面元素超时，尝试继续处理")
                    
                    # 获取页面内容
                    try:
                        html = driver.page_source
                        if not html:
                            raise ValueError("页面内容为空")
                        html_lower = html.lower()
                    except Exception as e:
                        logger.error(f"获取页面内容时出错: {str(e)}")
                        if retry_count < max_retries:
                            retry_count += 1
                            continue
                        return ProductStatus.UNKNOWN, None
                    
                    # 检查是否是404页面
                    not_found_indicators = [
                        "404",
                        "page not found",
                        "找不到页面",
                        "页面不存在",
                        "product is not available",
                        "product not found"
                    ]
                    
                    # 快速检查404状态
                    try:
                        # 1. 检查URL和标题
                        current_url = driver.current_url.lower()
                        title = driver.title.lower()
                        
                        if any(x in current_url or x in title for x in ["404", "error", "not found"]):
                            return ProductStatus.OFF_SHELF, None
                        
                        # 2. 检查页面内容
                        if any(x in html_lower for x in not_found_indicators):
                            return ProductStatus.OFF_SHELF, None
                        
                    except Exception as e:
                        logger.warning(f"检查404状态时出错: {str(e)}")
                    
                    # 快速检查商品状态
                    try:
                        # 售罄状态
                        if "NOTIFY ME WHEN AVAILABLE" in html:
                            return ProductStatus.SOLD_OUT, None
                        
                        # 可购买状态
                        buy_keywords = ['ADD TO BAG', 'add to bag', 'add to my bag', 'ADD TO MY BAG', 'BUY NOW']
                        if any(keyword in html for keyword in buy_keywords):
                            # 快速提取价格
                            price = None
                            try:
                                price_elements = driver.find_elements(By.XPATH, "//*[contains(@class, 'price') or contains(text(), '$')]")
                                for elem in price_elements:
                                    if '$' in elem.text:
                                        price = elem.text.strip()
                                        break
                            except Exception as e:
                                logger.warning(f"提取价格时出错: {str(e)}")
                            return ProductStatus.IN_STOCK, price
                        
                        return ProductStatus.UNKNOWN, None
                        
                    except Exception as e:
                        logger.warning(f"检查商品状态时出错: {str(e)}")
                        if retry_count < max_retries:
                            retry_count += 1
                            continue
                        return ProductStatus.UNKNOWN, None
                    
                except TimeoutException:
                    logger.error(f"页面加载超时: {url}")
                    if retry_count < max_retries:
                        retry_count += 1
                        continue
                    return ProductStatus.UNKNOWN, None
                    
                except WebDriverException as e:
                    logger.error(f"WebDriver 错误: {str(e)}")
                    if retry_count < max_retries:
                        retry_count += 1
                        continue
                    return ProductStatus.UNKNOWN, None
                    
                finally:
                    if driver:
                        try:
                            driver.quit()
                        except Exception as e:
                            logger.warning(f"关闭WebDriver时出错: {str(e)}")
                    
            except Exception as e:
                logger.error(f"检查商品状态时出错 ({url}): {str(e)}")
                logger.error(f"错误类型: {type(e).__name__}")
                if retry_count < max_retries:
                    retry_count += 1
                    continue
                return ProductStatus.UNKNOWN, None
            
            finally:
                if driver:
                    try:
                        driver.quit()
                    except:
                        pass
            
            # 如果执行到这里，说明成功完成了检查
            break
            
        return ProductStatus.UNKNOWN, None

    async def check_all_items(self) -> List[Notification]:
        """检查所有商品状态"""
        notifications = []
        items_to_check = list(self.monitored_items.items())
        
        # 创建信号量来限制并发数量
        semaphore = asyncio.Semaphore(3)  # 最多同时运行3个检查任务
        
        async def check_with_semaphore(url: str, previous_status: ProductStatus) -> Optional[Tuple[str, ProductStatus, Optional[str]]]:
            async with semaphore:
                try:
                    current_status, price = await self.check_item_status(url)
                    return url, current_status, price
                except Exception as e:
                    logger.error(f"检查商品状态时出错 ({url}): {str(e)}")
                    return None
        
        # 创建所有检查任务
        tasks = []
        for url, previous_status in items_to_check:
            task = asyncio.create_task(check_with_semaphore(url, previous_status))
            tasks.append(task)
        
        # 等待所有任务完成，但设置总体超时
        try:
            results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=60)
            
            for result in results:
                if result is None or isinstance(result, Exception):
                    continue
                    
                url, current_status, price = result
                previous_status = self.monitored_items.get(url)
                
                # 记录检查结果
                logger.info(f"商品状态检查 - {url.split('/')[-1]} ({url}):")
                logger.info(f"  当前状态: {current_status.name.lower()}")
                logger.info(f"  之前状态: {previous_status.name.lower()}")
                
                # 如果状态发生变化，创建通知
                if current_status != previous_status and current_status != ProductStatus.UNKNOWN:
                    notification = Notification(
                        url=url,
                        old_status=previous_status,
                        new_status=current_status,
                        price=price
                    )
                    notifications.append(notification)
                    
                    # 更新状态
                    self.monitored_items[url] = current_status
                    
                # 如果连续返回unknown状态，记录警告
                elif current_status == ProductStatus.UNKNOWN:
                    if url in self.unknown_count:
                        self.unknown_count[url] += 1
                        if self.unknown_count[url] >= 3:  # 连续3次unknown
                            logger.warning(f"商品 {url} 连续 {self.unknown_count[url]} 次返回unknown状态")
                    else:
                        self.unknown_count[url] = 1
                else:
                    # 重置unknown计数
                    self.unknown_count.pop(url, None)
                    
        except asyncio.TimeoutError:
            logger.error("检查所有商品状态超时")
        except Exception as e:
            logger.error(f"检查商品状态时出错: {str(e)}")
            
        return notifications 