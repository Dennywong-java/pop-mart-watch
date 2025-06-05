"""
监控模块，负责检查商品可用性
"""
import asyncio
import logging
from typing import Optional, Dict, List
import aiohttp
from bs4 import BeautifulSoup
from src.config import config
import json
import re
import os

logger = logging.getLogger(__name__)

class ProductMonitor:
    """
    商品监控类
    负责检查商品页面的可用性状态
    """
    
    # 监控项目文件路径
    MONITORED_ITEMS_FILE = 'monitored_items.json'
    
    # 可购买状态的关键词
    AVAILABLE_KEYWORDS = [
        'add to bag',
        'add to cart',
        'buy now',
        'purchase',
        'checkout',
        'in stock',
        'add to shopping bag'
    ]
    
    # 售罄状态的关键词
    SOLD_OUT_KEYWORDS = [
        'sold out',
        'out of stock',
        'currently unavailable',
        'not available',
        'notify me when available',
        'coming soon',
        'temporarily unavailable'
    ]

    @staticmethod
    def parse_product_url(url: str) -> Dict[str, str]:
        """
        从URL中解析产品信息
        
        Args:
            url: 商品URL
            
        Returns:
            Dict[str, str]: 包含产品ID和名称的字典
        """
        try:
            # 匹配 /products/{id}/{name} 格式
            pattern = r'/products/(\d+)/([^/]+)'
            match = re.search(pattern, url)
            if match:
                product_id = match.group(1)
                product_name = match.group(2).replace('-', ' ')
                return {
                    'id': product_id,
                    'name': product_name,
                    'url': url
                }
            return {}
        except Exception as e:
            logger.error(f"Error parsing product URL {url}: {str(e)}")
            return {}

    @staticmethod
    def load_monitored_items() -> List[Dict[str, str]]:
        """
        加载监控项目列表
        
        Returns:
            List[Dict[str, str]]: 监控项目列表
        """
        try:
            if os.path.exists(ProductMonitor.MONITORED_ITEMS_FILE):
                with open(ProductMonitor.MONITORED_ITEMS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return []
        except Exception as e:
            logger.error(f"Error loading monitored items: {str(e)}")
            return []

    @staticmethod
    def save_monitored_items(items: List[Dict[str, str]]) -> bool:
        """
        保存监控项目列表
        
        Args:
            items: 监控项目列表
            
        Returns:
            bool: 是否保存成功
        """
        try:
            with open(ProductMonitor.MONITORED_ITEMS_FILE, 'w', encoding='utf-8') as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"Error saving monitored items: {str(e)}")
            return False

    @staticmethod
    def add_monitored_item(url: str) -> bool:
        """
        添加监控项目
        
        Args:
            url: 商品URL
            
        Returns:
            bool: 是否添加成功
        """
        try:
            # 解析URL
            product_info = ProductMonitor.parse_product_url(url)
            if not product_info:
                logger.error(f"Invalid product URL: {url}")
                return False
            
            # 加载现有项目
            items = ProductMonitor.load_monitored_items()
            
            # 检查是否已存在
            if any(item['id'] == product_info['id'] for item in items):
                logger.warning(f"Product {product_info['id']} already monitored")
                return False
            
            # 添加新项目
            items.append(product_info)
            
            # 保存更新后的列表
            return ProductMonitor.save_monitored_items(items)
        except Exception as e:
            logger.error(f"Error adding monitored item: {str(e)}")
            return False

    @staticmethod
    def remove_monitored_item(product_id: str) -> bool:
        """
        移除监控项目
        
        Args:
            product_id: 产品ID
            
        Returns:
            bool: 是否移除成功
        """
        try:
            # 加载现有项目
            items = ProductMonitor.load_monitored_items()
            
            # 移除指定项目
            original_length = len(items)
            items = [item for item in items if item['id'] != product_id]
            
            # 如果列表长度没变，说明没找到要删除的项目
            if len(items) == original_length:
                logger.warning(f"Product {product_id} not found in monitored items")
                return False
            
            # 保存更新后的列表
            return ProductMonitor.save_monitored_items(items)
        except Exception as e:
            logger.error(f"Error removing monitored item: {str(e)}")
            return False

    @staticmethod
    def _extract_product_id(url: str) -> Optional[str]:
        """
        从URL中提取商品ID
        
        Args:
            url: 商品URL
            
        Returns:
            Optional[str]: 商品ID或None
        """
        try:
            product_info = ProductMonitor.parse_product_url(url)
            return product_info.get('id')
        except Exception as e:
            logger.error(f"Error extracting product ID from {url}: {str(e)}")
            return None

    @staticmethod
    async def get_product_info(url: str, session: aiohttp.ClientSession) -> Dict[str, str]:
        """
        获取商品信息，包括图片URL
        
        Args:
            url: 商品URL
            session: aiohttp会话
            
        Returns:
            Dict[str, str]: 包含商品信息的字典
        """
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.popmart.com/',
            'Connection': 'keep-alive',
            'sec-ch-ua': '"Not A(Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"macOS"',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1'
        }
        
        try:
            # 从HTML获取商品信息
            async with session.get(url, headers=headers, timeout=30) as html_response:
                if html_response.status == 200:
                    html = await html_response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # 尝试从Next.js数据中获取信息
                    next_data = soup.find('script', id='__NEXT_DATA__')
                    if next_data:
                        try:
                            data = json.loads(next_data.string)
                            product_data = data.get('props', {}).get('pageProps', {}).get('product', {})
                            if product_data:
                                title = product_data.get('title', '') or product_data.get('name', '')
                                images = product_data.get('images', [])
                                image_url = images[0].get('url', '') if images else None
                                
                                if title and image_url:
                                    return {
                                        'image_url': image_url,
                                        'title': title
                                    }
                        except:
                            pass
                    
                    # 尝试从页面元数据中获取信息
                    title = None
                    image_url = None
                    
                    # 从JSON-LD获取信息
                    json_ld = soup.find('script', type='application/ld+json')
                    if json_ld:
                        try:
                            data = json.loads(json_ld.string)
                            if isinstance(data, dict):
                                title = data.get('name')
                                image_url = data.get('image')
                                if isinstance(image_url, list) and image_url:
                                    image_url = image_url[0]
                        except:
                            pass
                    
                    # 从 og:title 和 og:image 元标签获取信息
                    if not title:
                        og_title = soup.find('meta', property='og:title')
                        if og_title:
                            title = og_title.get('content', '').split('-')[0].strip()
                    
                    if not image_url:
                        og_image = soup.find('meta', property='og:image')
                        if og_image:
                            image_url = og_image.get('content')
                    
                    # 如果没有找到 og 标签，尝试其他方法
                    if not title:
                        title_tag = soup.find('h1', class_='product-title') or soup.find('title')
                        if title_tag:
                            title = title_tag.text.split('|')[0].strip()
                    
                    if not image_url:
                        img_tags = soup.find_all('img', class_='product-image') or soup.find_all('img', class_='ant-image-img')
                        if img_tags:
                            for img in img_tags:
                                src = img.get('src') or img.get('data-src')
                                if src and ('1200x1200' in src or 'product' in src.lower()):
                                    image_url = src
                                    break
                    
                    logger.info(f"Product info from HTML for {url}:")
                    logger.info(f"Title: {title}")
                    logger.info(f"Image URL: {image_url}")
                    
                    return {
                        'image_url': image_url,
                        'title': title
                    }
            
            logger.warning(f"Failed to fetch product info from {url}")
            return {}
        except asyncio.TimeoutError:
            logger.error(f"Timeout while fetching product info from {url}")
            return {}
        except Exception as e:
            logger.error(f"Error getting product info from {url}: {str(e)}")
            return {}
    
    @staticmethod
    def _text_exists(soup: BeautifulSoup, keywords: list) -> bool:
        """
        检查页面中是否存在指定关键词（不区分大小写）
        
        Args:
            soup: BeautifulSoup 对象
            keywords: 要搜索的关键词列表
            
        Returns:
            bool: 是否找到任何关键词
        """
        # 获取页面中所有文本
        page_text = soup.get_text().lower()
        
        # 检查是否存在任何关键词
        return any(keyword.lower() in page_text for keyword in keywords)

    @staticmethod
    async def check_product_availability(url: str, session: aiohttp.ClientSession) -> Optional[bool]:
        """
        检查商品是否可购买
        
        Args:
            url: 商品URL
            session: aiohttp会话
            
        Returns:
            Optional[bool]: True表示可购买，False表示不可购买，None表示检查出错
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://www.popmart.com/',
                'Connection': 'keep-alive',
                'sec-ch-ua': '"Not A(Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"macOS"',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-User': '?1',
                'Upgrade-Insecure-Requests': '1'
            }
            
            logger.info(f"开始检查商品 URL: {url}")
            
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # 检查所有按钮和链接
                    buttons = soup.find_all(['button', 'a', 'div'])
                    logger.debug(f"找到 {len(buttons)} 个可能的按钮/链接元素")
                    
                    for button in buttons:
                        # 获取按钮的所有文本内容
                        button_text = button.get_text(strip=True, separator=' ').lower()
                        button_class = ' '.join(button.get('class', [])).lower()
                        button_id = button.get('id', '').lower()
                        
                        # 记录按钮详细信息
                        if button_text:
                            logger.debug(f"按钮文本: '{button_text}'")
                            logger.debug(f"按钮类名: '{button_class}'")
                            logger.debug(f"按钮ID: '{button_id}'")
                            
                            # 检查是否包含可购买关键词
                            for keyword in ProductMonitor.AVAILABLE_KEYWORDS:
                                if keyword.lower() in button_text:
                                    logger.info(f"找到可购买关键词: '{keyword}' in '{button_text}'")
                                    
                                    # 检查是否同时包含售罄关键词
                                    has_soldout = any(soldout.lower() in button_text or soldout.lower() in button_class 
                                                    for soldout in ProductMonitor.SOLD_OUT_KEYWORDS)
                                    
                                    if not has_soldout:
                                        # 检查按钮是否被禁用
                                        is_disabled = (
                                            button.get('disabled') is not None or
                                            'disabled' in button_class or
                                            'disabled' in button_id or
                                            'sold-out' in button_class or
                                            'soldout' in button_class
                                        )
                                        
                                        if not is_disabled:
                                            logger.info(f"商品可购买: 找到有效的购买按钮 '{button_text}'")
                                            return True
                                        else:
                                            logger.info(f"按钮已禁用: '{button_text}'")
                    
                    # 如果没有找到可购买按钮，检查页面源代码中的状态
                    scripts = soup.find_all('script', type='application/json')
                    for script in scripts:
                        try:
                            data = json.loads(script.string)
                            if isinstance(data, dict):
                                # 记录找到的所有相关状态
                                logger.debug(f"找到 JSON 数据: {json.dumps(data, indent=2)}")
                                
                                # 检查各种可能的状态字段
                                stock_status = data.get('stock_status', '')
                                inventory = data.get('inventory', {})
                                purchasable = data.get('purchasable', False)
                                
                                if stock_status:
                                    logger.info(f"库存状态: {stock_status}")
                                if inventory:
                                    logger.info(f"库存信息: {inventory}")
                                if purchasable is not None:
                                    logger.info(f"可购买状态: {purchasable}")
                                
                                # 如果找到任何表明可购买的状态
                                if (stock_status and 'in_stock' in stock_status.lower()) or \
                                   (inventory and inventory.get('available_quantity', 0) > 0) or \
                                   purchasable:
                                    return True
                        except json.JSONDecodeError:
                            continue
                    
                    logger.warning(f"商品 {url} 可能已售罄: 未找到有效的购买按钮或库存信息")
                    return False
                else:
                    logger.error(f"请求失败: {url}, 状态码: {response.status}")
                    return None
        except Exception as e:
            logger.error(f"检查商品时发生错误 {url}: {str(e)}")
            return None

    @staticmethod
    async def monitor_with_delay(url: str, session: aiohttp.ClientSession) -> Optional[bool]:
        """
        带延迟的商品监控
        
        Args:
            url: 商品URL
            session: aiohttp会话
            
        Returns:
            Optional[bool]: True表示可购买，False表示不可购买，None表示检查出错
        """
        await asyncio.sleep(config.request_delay)
        return await ProductMonitor.check_product_availability(url, session) 