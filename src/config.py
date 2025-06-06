"""
配置模块，负责加载和管理配置
"""
import os
import yaml
import logging.config
from dataclasses import dataclass
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

@dataclass
class DiscordConfig:
    token: str
    channel_id: int
    guild_id: int

@dataclass
class MonitorConfig:
    check_interval: int
    request_delay: int
    allowed_domains: List[str]

@dataclass
class StorageConfig:
    data_file: str

@dataclass
class LoggingConfig:
    level: str
    file: str
    console: bool
    format: str
    max_size: int
    backup_count: int
    third_party_levels: Dict[str, str]

@dataclass
class Config:
    discord: DiscordConfig
    monitor: MonitorConfig
    storage: StorageConfig
    logging: LoggingConfig

    @staticmethod
    def load(config_path: str = "config.yaml") -> 'Config':
        """加载配置文件"""
        try:
            # 读取配置文件
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)

            # 创建配置对象
            discord_config = DiscordConfig(
                token=config_data['discord']['token'],
                channel_id=config_data['discord']['channel_id'],
                guild_id=config_data['discord']['guild_id']
            )

            monitor_config = MonitorConfig(
                check_interval=config_data['monitor']['check_interval'],
                request_delay=config_data['monitor']['request_delay'],
                allowed_domains=config_data['monitor']['allowed_domains']
            )

            storage_config = StorageConfig(
                data_file=config_data['storage']['data_file']
            )

            logging_config = LoggingConfig(
                level=config_data['logging']['level'],
                file=config_data['logging']['file'],
                console=config_data['logging']['console'],
                format=config_data['logging']['format'],
                max_size=config_data['logging']['max_size'],
                backup_count=config_data['logging']['backup_count'],
                third_party_levels=config_data['logging']['third_party_levels']
            )

            config = Config(
                discord=discord_config,
                monitor=monitor_config,
                storage=storage_config,
                logging=logging_config
            )

            # 配置日志
            os.makedirs(os.path.dirname(config.logging.file), exist_ok=True)
            
            logging_config = {
                'version': 1,
                'disable_existing_loggers': False,
                'formatters': {
                    'standard': {
                        'format': config.logging.format
                    },
                },
                'handlers': {
                    'file': {
                        'level': config.logging.level,
                        'class': 'logging.handlers.RotatingFileHandler',
                        'filename': config.logging.file,
                        'maxBytes': config.logging.max_size,
                        'backupCount': config.logging.backup_count,
                        'formatter': 'standard',
                        'encoding': 'utf-8',
                    },
                },
                'loggers': {
                    '': {
                        'handlers': ['file'],
                        'level': config.logging.level,
                        'propagate': True
                    }
                }
            }

            # 如果启用控制台输出，添加控制台处理器
            if config.logging.console:
                logging_config['handlers']['console'] = {
                    'level': config.logging.level,
                    'class': 'logging.StreamHandler',
                    'formatter': 'standard'
                }
                logging_config['loggers']['']['handlers'].append('console')

            # 配置第三方库的日志级别
            for logger_name, level in config.logging.third_party_levels.items():
                logging_config['loggers'][logger_name] = {
                    'level': level,
                    'handlers': ['file'] + (['console'] if config.logging.console else []),
                    'propagate': False
                }

            logging.config.dictConfig(logging_config)
            logger = logging.getLogger(__name__)
            logger.info("配置加载成功")

            return config

        except Exception as e:
            print(f"加载配置文件失败: {str(e)}")
            raise

# 创建全局配置实例
config = Config.load() 