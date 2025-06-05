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
    """配置管理类"""
    _instance = None
    _config: Dict[str, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
            cls._instance._load_config()
        return cls._instance

    def _load_config(self):
        """加载配置文件"""
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.yaml')
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                self._config = yaml.safe_load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"配置文件未找到：{config_path}")
        except yaml.YAMLError as e:
            raise ValueError(f"配置文件格式错误：{str(e)}")
        
        self._setup_logging()

    def _setup_logging(self):
        """设置日志配置"""
        log_config = self._config.get('logging', {})
        log_level = getattr(logging, log_config.get('level', 'INFO'))
        log_file = log_config.get('file', 'logs/bot.log')
        console_output = log_config.get('console', True)

        # 创建日志目录
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

        # 配置日志
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler() if console_output else logging.NullHandler()
            ]
        )

    @property
    def discord_token(self) -> str:
        """获取 Discord 令牌"""
        return self._config['discord']['token']

    @property
    def discord_channel_id(self) -> int:
        """获取 Discord 频道 ID"""
        return self._config['discord']['channel_id']

    @property
    def command_prefix(self) -> str:
        """获取命令前缀"""
        return self._config['discord']['command_prefix']

    @property
    def check_interval(self) -> int:
        """获取检查间隔时间"""
        return self._config['monitor']['check_interval']

    @property
    def request_delay(self) -> int:
        """获取请求延迟时间"""
        return self._config['monitor']['request_delay']

    @property
    def allowed_domains(self) -> list:
        """获取允许的域名列表"""
        return self._config['monitor']['allowed_domains']

    @property
    def storage_file(self) -> str:
        """获取存储文件路径"""
        return self._config['storage']['data_file']

# 创建全局配置实例
config = Config() 