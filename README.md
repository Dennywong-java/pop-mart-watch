# POP MART 商品监控机器人

一个用于监控 POP MART 商品库存状态的 Discord 机器人。

## 功能特点

- 实时监控商品库存状态
- Discord 通知
- 自动重试和错误恢复
- 支持多商品同时监控
- 资源使用限制（CPU和内存）

## 系统要求

- Python 3.9 或更高版本
- 系统内存 >= 2GB
- Ubuntu/Debian 系统（如果在 EC2 上部署）

## 在 EC2 上部署

### 1. 准备工作

确保您的 EC2 实例满足以下条件：
- Ubuntu 系统
- Python 3.9 或更高版本
- 至少 2GB 内存
- 具有 sudo 权限的用户

### 2. 克隆项目

```bash
# 克隆项目
git clone https://github.com/YOUR_USERNAME/pop-mart-watch.git
cd pop-mart-watch
```

### 3. 配置项目

```bash
# 复制示例配置文件
cp config.yaml.example config.yaml

# 编辑配置文件
nano config.yaml
```

需要配置的重要项目：
- `discord.token`: Discord 机器人令牌
- `discord.channel_id`: 通知消息发送的频道 ID
- `discord.guild_id`: Discord 服务器 ID

### 4. 运行部署脚本

```bash
# 使脚本可执行
chmod +x setup.sh

# 运行部署脚本
./setup.sh
```

部署脚本会：
- 创建必要的目录
- 设置 Python 虚拟环境
- 安装依赖
- 创建系统服务
- 启动监控服务

### 5. 管理服务

```bash
# 查看服务状态
sudo systemctl status popmart-watch

# 查看服务日志（systemd日志）
sudo journalctl -u popmart-watch -f

# 查看程序日志（包含启动、退出信息）
tail -f logs/service.log

# 重启服务
sudo systemctl restart popmart-watch

# 停止服务
sudo systemctl stop popmart-watch
```

### 6. 使用 Discord 命令

机器人使用斜杠命令系统，支持以下命令：

- `/watch <url>` - 添加商品到监控列表
  - `url`: 商品页面的 URL（机器人会自动提取商品 ID 和名称）
  
  示例：
  ```
  /watch https://www.popmart.com/products/578/LABUBU-Time-to-chill-Vinyl-Plush-Doll
  ```

- `/unwatch <url>` - 从监控列表中移除商品
  - `url`: 要移除的商品 URL

- `/list` - 显示所有正在监控的商品

- `/status` - 显示机器人状态

## 故障排除

### 1. 服务无法启动

检查以下几点：
- 配置文件是否正确（`config.yaml`）
- Discord 令牌是否有效
- 日志文件中是否有错误信息

```bash
# 检查配置文件
cat config.yaml

# 检查日志
tail -f logs/service.log
```

### 2. 内存使用过高

服务配置了以下资源限制：
- 内存限制：512MB
- CPU限制：最多使用30%

如果需要调整限制，编辑服务文件：
```bash
sudo nano /etc/systemd/system/popmart-watch.service
```

### 3. 程序频繁重启

检查日志文件以确定重启原因：
```bash
tail -f logs/service.log
```

可能的原因：
- 网络连接问题
- Discord API 限制
- 程序错误

## 安全建议

1. 不要将以下文件提交到 Git：
   - `config.yaml`（包含敏感信息）
   - `monitored_items.json`（监控配置）
   - `logs/` 目录（日志文件）

2. 确保 EC2 安全组设置正确：
   - 只开放必要的端口
   - 限制 SSH 访问来源

3. 定期更新系统和依赖：
   ```bash
   sudo apt update && sudo apt upgrade
   pip install --upgrade -r requirements.txt
   ```

## 贡献

欢迎提交 Issue 和 Pull Request！

## 许可证

MIT License 