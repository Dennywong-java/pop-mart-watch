# Pop Mart Watch Bot

一个用于监控 Pop Mart 商品库存的 Discord 机器人。

## 功能特点

- 实时监控 Pop Mart 商品页面
- Discord 机器人交互界面
- 支持添加/删除监控商品
- 库存状态变化即时通知
- 可配置监控间隔时间
- 完整的日志记录
- YAML 配置文件支持

## 项目结构

```
pop-mart-watch/
├── src/                    # 源代码目录
│   ├── __init__.py        # 包初始化文件
│   ├── config.py          # 配置管理模块
│   ├── storage.py         # 数据存储模块
│   ├── monitor.py         # 商品监控模块
│   └── discord_bot.py     # Discord机器人模块
├── data/                   # 数据存储目录
│   └── monitored_items.json
├── logs/                   # 日志目录
│   └── bot.log
├── config.yaml            # 配置文件
├── main.py                # 主程序入口
└── requirements.txt       # 依赖管理
```

## 环境要求

- Python 3.8+
- Discord Bot Token
- 配置文件 (config.yaml)

## 安装步骤

1. 克隆仓库：
```bash
git clone https://github.com/yourusername/pop-mart-watch.git
cd pop-mart-watch
```

2. 安装依赖：
```bash
pip install -r requirements.txt
```

3. 配置 `config.yaml`：
```yaml
# Discord 配置
discord:
  token: "your-discord-token-here"  # Discord 机器人令牌
  channel_id: 123456789            # 通知消息发送的频道 ID
  command_prefix: "!"              # 机器人命令前缀

# 监控配置
monitor:
  check_interval: 30               # 检查间隔时间（秒）
  request_delay: 1                 # 请求间隔时间（秒）
  allowed_domains:                 # 允许监控的域名列表
    - "popmart.com"
    - "pop-mart.com"

# 存储配置
storage:
  data_file: "data/monitored_items.json"  # 数据存储文件路径

# 日志配置
logging:
  level: "INFO"                    # 日志级别
  file: "logs/bot.log"            # 日志文件路径
  console: true                    # 是否在控制台输出日志
```

4. 创建必要的目录：
```bash
mkdir -p data logs
```

5. 运行机器人：
```bash
python main.py
```

## Discord 命令

- `!watch <url>` - 添加商品到监控列表
  - 示例：`!watch https://www.popmart.com/products/123`
  - 仅支持 Pop Mart 官方网站链接

- `!unwatch <url>` - 移除商品监控
  - 示例：`!unwatch https://www.popmart.com/products/123`

- `!list` - 查看所有监控商品
  - 显示所有正在监控的商品及其状态

- `!status` - 查看机器人状态
  - 显示监控商品数量
  - 显示检查间隔时间
  - 显示运行状态

## 配置说明

### Discord 配置
- `token`: Discord 机器人令牌，从 Discord Developer Portal 获取
- `channel_id`: 通知消息发送的频道 ID
- `command_prefix`: 机器人命令前缀，默认为 "!"

### 监控配置
- `check_interval`: 检查商品状态的时间间隔（秒）
- `request_delay`: 每次请求之间的延迟时间（秒）
- `allowed_domains`: 允许监控的网站域名列表

### 存储配置
- `data_file`: 监控商品数据的存储文件路径

### 日志配置
- `level`: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- `file`: 日志文件保存路径
- `console`: 是否在控制台输出日志

## 注意事项

1. 请合理设置检查间隔时间，避免过于频繁的请求
2. 建议在服务器或长期运行的机器上部署
3. 确保 Discord 机器人有足够的权限发送消息和嵌入内容
4. 定期检查日志文件，及时发现和处理潜在问题
5. 建议将配置文件添加到 .gitignore 中，避免泄露敏感信息

## 错误处理

1. 如果机器人无法启动，请检查：
   - Discord Token 是否正确
   - 配置文件格式是否正确
   - 必要的目录是否已创建

2. 如果监控不工作，请检查：
   - 网络连接是否正常
   - 商品 URL 是否正确
   - 日志文件中是否有错误信息

## 贡献指南

欢迎提交 Issue 和 Pull Request 来改进这个项目。在提交之前，请确保：

1. 代码符合 PEP 8 规范
2. 添加了适当的注释和文档
3. 所有测试都已通过

## 许可证

MIT License 