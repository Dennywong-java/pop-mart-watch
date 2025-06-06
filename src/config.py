"""
配置模块，负责加载和管理配置
"""
import os
import yaml
import logging
import shutil
from typing import Dict, Any

logger = logging.getLogger(__name__)

def load_yaml(file_path: str) -> Dict[str, Any]:
    """
    加载YAML文件
    
    Args:
        file_path: YAML文件路径
        
    Returns:
        Dict[str, Any]: 配置字典
    """
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        return {}
    except Exception as e:
        logger.error(f"Error loading {file_path}: {str(e)}")
        return {}

def load_config() -> Dict[str, Any]:
    """
    加载配置
    如果配置文件不存在，提示用户从示例文件创建
    
    Returns:
        Dict[str, Any]: 配置字典
    """
    config_file = 'config.yaml'
    example_file = 'config.example.yaml'
    
    # 检查配置文件是否存在
    if not os.path.exists(config_file):
        if os.path.exists(example_file):
            error_msg = (
                f"\n{'='*80}\n"
                f"错误: 配置文件 '{config_file}' 不存在！\n\n"
                f"请复制示例配置文件并进行必要的修改：\n"
                f"1. 复制 {example_file} 到 {config_file}\n"
                f"2. 编辑 {config_file} 并设置您的 Discord 令牌和频道 ID\n"
                f"{'='*80}"
            )
        else:
            error_msg = (
                f"\n{'='*80}\n"
                f"错误: 配置文件 '{config_file}' 和示例配置文件 '{example_file}' 都不存在！\n"
                f"请确保项目文件完整。\n"
                f"{'='*80}"
            )
        raise FileNotFoundError(error_msg)
    
    # 加载配置
    config = load_yaml(config_file)
    if not config:
        raise ValueError(f"Failed to load config from {config_file}")
    
    # 验证必要的配置项
    if not config.get('discord', {}).get('token'):
        raise ValueError("Discord token not configured in config.yaml")
    if not config.get('discord', {}).get('channel_id'):
        raise ValueError("Discord channel_id not configured in config.yaml")
    
    return config

# 加载配置
config = load_config()

class Config:
    """配置类"""
    
    def __init__(self):
        """初始化配置"""
        self.discord_token = ""
        self.discord_channel_id = 0
        self.discord_guild_id = 0
        self.check_interval = 60
        self.request_delay = 1
        self.allowed_domains = []
        self.log_level = "INFO"
        self.log_file = "logs/bot.log"
        self.log_console = True
        self.log_format = '%(asctime)s - %(levelname)s - %(message)s'
        self.third_party_levels = {
            'discord': 'WARNING',
            'selenium': 'WARNING',
            'urllib3': 'WARNING',
            'asyncio': 'WARNING'
        }
        
        # 加载配置前先设置基本日志
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler()]
        )
        
        self.load_config()
        
        # 加载配置后更新日志设置
        self.setup_logging()
        
    def setup_logging(self):
        """设置日志配置"""
        # 创建日志目录
        os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
        
        # 获取日志级别
        log_level = getattr(logging, self.log_level.upper(), logging.INFO)
        
        # 清除现有的处理器
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # 设置新的处理器
        handlers = []
        
        # 文件处理器
        file_handler = logging.FileHandler(self.log_file)
        file_handler.setFormatter(logging.Formatter(self.log_format))
        handlers.append(file_handler)
        
        # 控制台处理器
        if self.log_console:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(logging.Formatter(self.log_format))
            handlers.append(console_handler)
        
        # 应用配置
        logging.basicConfig(
            level=log_level,
            handlers=handlers
        )
        
        # 设置第三方库的日志级别
        for logger_name, level in self.third_party_levels.items():
            level_value = getattr(logging, level.upper(), logging.WARNING)
            logging.getLogger(logger_name).setLevel(level_value)
        
        logger.info("日志配置已更新")
        
    def load_config(self):
        """加载配置文件"""
        try:
            # 首先尝试加载 config.yaml
            config_file = 'config.yaml'
            if not os.path.exists(config_file):
                # 如果不存在，尝试加载 config.example.yaml
                config_file = 'config.example.yaml'
                if not os.path.exists(config_file):
                    raise FileNotFoundError("未找到配置文件")
            
            with open(config_file, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)
            
            # Discord 配置
            discord_config = config_data.get('discord', {})
            self.discord_token = discord_config.get('token', "")
            self.discord_channel_id = discord_config.get('channel_id', 0)
            self.discord_guild_id = discord_config.get('guild_id', 0)
            
            # 监控配置
            monitor_config = config_data.get('monitor', {})
            self.check_interval = monitor_config.get('check_interval', 60)
            self.request_delay = monitor_config.get('request_delay', 1)
            self.allowed_domains = monitor_config.get('allowed_domains', [])
            
            # 日志配置
            logging_config = config_data.get('logging', {})
            self.log_level = logging_config.get('level', "INFO")
            self.log_file = logging_config.get('file', "logs/bot.log")
            self.log_console = logging_config.get('console', True)
            self.log_format = logging_config.get('format', '%(asctime)s - %(levelname)s - %(message)s')
            self.third_party_levels = logging_config.get('third_party_levels', {
                'discord': 'WARNING',
                'selenium': 'WARNING',
                'urllib3': 'WARNING',
                'asyncio': 'WARNING'
            })
            
            logger.info("配置加载成功")
            
        except Exception as e:
            logger.error(f"加载配置文件时出错: {str(e)}")
            raise

# 创建全局配置实例
config = Config() 