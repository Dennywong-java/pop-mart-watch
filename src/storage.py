"""
存储模块，负责管理监控项目的持久化
"""
import json
import logging
import os
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class MonitorStore:
    """
    监控项目存储类
    负责监控项目的加载和保存
    """
    
    def __init__(self):
        """
        初始化存储类
        """
        # 确保数据目录存在
        self.data_dir = os.path.join(os.getcwd(), 'data')
        os.makedirs(self.data_dir, exist_ok=True)
        
        # 设置存储文件路径
        self.file_path = os.path.join(self.data_dir, 'monitored_items.json')
        
        # 初始化存储列表
        self.items: List[Dict[str, Any]] = []
        
        # 加载数据
        self.load_items()
    
    def load_items(self) -> None:
        """
        从文件加载监控项目列表
        如果文件不存在或为空，则初始化为空列表
        """
        try:
            if os.path.exists(self.file_path) and os.path.getsize(self.file_path) > 0:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    self.items = json.load(f)
                logger.info(f"已加载 {len(self.items)} 个监控项目")
            else:
                logger.info("监控项目文件不存在或为空，初始化为空列表")
                self.items = []
                self.save_items()  # 创建初始文件
        except json.JSONDecodeError as e:
            logger.error(f"监控项目文件格式错误: {str(e)}")
            logger.info("重置为空列表并备份原文件")
            # 如果文件存在但格式错误，创建备份
            if os.path.exists(self.file_path):
                backup_path = f"{self.file_path}.bak"
                os.rename(self.file_path, backup_path)
            self.items = []
            self.save_items()
        except Exception as e:
            logger.error(f"加载监控项目时出错: {str(e)}")
            self.items = []
    
    def save_items(self) -> None:
        """
        保存监控项目列表到文件
        """
        try:
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(self.items, f, ensure_ascii=False, indent=2)
            logger.info(f"已保存 {len(self.items)} 个监控项目")
        except Exception as e:
            logger.error(f"保存监控项目时出错: {str(e)}")
    
    def add_item(self, item: Dict[str, Any]) -> bool:
        """
        添加监控项目
        
        Args:
            item: 监控项目信息
            
        Returns:
            bool: 是否添加成功
        """
        try:
            # 检查是否已存在
            if any(x.get('id') == item.get('id') for x in self.items):
                logger.warning(f"监控项目已存在: {item.get('id')}")
                return False
            
            self.items.append(item)
            self.save_items()
            logger.info(f"已添加监控项目: {item.get('id')}")
            return True
        except Exception as e:
            logger.error(f"添加监控项目时出错: {str(e)}")
            return False
    
    def remove_item(self, item_id: str) -> bool:
        """
        移除监控项目
        
        Args:
            item_id: 监控项目ID
            
        Returns:
            bool: 是否移除成功
        """
        try:
            original_length = len(self.items)
            self.items = [x for x in self.items if x.get('id') != item_id]
            
            if len(self.items) < original_length:
                self.save_items()
                logger.info(f"已移除监控项目: {item_id}")
                return True
            else:
                logger.warning(f"监控项目不存在: {item_id}")
                return False
        except Exception as e:
            logger.error(f"移除监控项目时出错: {str(e)}")
            return False
    
    def get_items(self) -> List[Dict[str, Any]]:
        """
        获取所有监控项目
        
        Returns:
            List[Dict[str, Any]]: 监控项目列表
        """
        return self.items.copy()  # 返回副本以防止外部修改 