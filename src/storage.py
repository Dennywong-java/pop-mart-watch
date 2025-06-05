"""
存储模块，用于处理数据的持久化存储
"""
import json
import os
from typing import Dict, Any
from src.config import config

class MonitorStore:
    """
    监控商品存储类
    负责管理监控商品的持久化存储和状态管理
    """
    def __init__(self):
        self.items: Dict[str, Any] = {}
        self._ensure_data_directory()
        self.load_items()

    def _ensure_data_directory(self) -> None:
        """确保数据目录存在"""
        os.makedirs(os.path.dirname(config.storage_file), exist_ok=True)

    def load_items(self) -> None:
        """
        从文件加载监控商品列表
        如果文件不存在，则初始化为空字典
        """
        try:
            with open(config.storage_file, 'r', encoding='utf-8') as f:
                self.items = json.load(f)
        except FileNotFoundError:
            self.items = {}

    def save_items(self) -> None:
        """
        将监控商品列表保存到文件
        """
        with open(config.storage_file, 'w', encoding='utf-8') as f:
            json.dump(self.items, f, ensure_ascii=False, indent=2)

    def add_item(self, url: str) -> bool:
        """
        添加商品到监控列表
        
        Args:
            url: 商品URL
            
        Returns:
            bool: 是否添加成功
        """
        if url not in self.items:
            self.items[url] = {"status": "unknown"}
            self.save_items()
            return True
        return False

    def remove_item(self, url: str) -> bool:
        """
        从监控列表中移除商品
        
        Args:
            url: 商品URL
            
        Returns:
            bool: 是否移除成功
        """
        if url in self.items:
            del self.items[url]
            self.save_items()
            return True
        return False

    def update_item_status(self, url: str, status: str) -> None:
        """
        更新商品状态
        
        Args:
            url: 商品URL
            status: 新状态
        """
        if url in self.items:
            self.items[url]["status"] = status
            self.save_items()

    def get_item_status(self, url: str) -> str:
        """
        获取商品状态
        
        Args:
            url: 商品URL
            
        Returns:
            str: 商品状态
        """
        return self.items.get(url, {}).get("status", "unknown") 