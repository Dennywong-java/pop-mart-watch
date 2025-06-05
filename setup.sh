#!/bin/bash

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}开始部署 POP MART 监控机器人...${NC}"

# 检查是否在项目根目录
if [ ! -f "main.py" ]; then
    echo -e "${RED}错误：请在项目根目录运行此脚本${NC}"
    exit 1
fi

# 创建并设置必要的目录
echo -e "\n${YELLOW}1. 创建必要的目录...${NC}"
mkdir -p logs data
chmod 755 logs data

# 初始化数据文件
echo -e "\n${YELLOW}2. 初始化数据文件...${NC}"
echo '[]' > data/monitored_items.json
chmod 644 data/monitored_items.json

# 创建并激活虚拟环境
echo -e "\n${YELLOW}3. 设置Python虚拟环境...${NC}"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate

# 安装依赖
echo -e "\n${YELLOW}4. 安装Python依赖...${NC}"
pip install -r requirements.txt

# 配置文件检查
echo -e "\n${YELLOW}5. 检查配置文件...${NC}"
if [ ! -f "config.yaml" ]; then
    echo -e "${RED}请注意：需要创建并配置 config.yaml 文件${NC}"
    cp config.example.yaml config.yaml
    chmod 644 config.yaml
    echo -e "请编辑 config.yaml 文件，设置您的 Discord 令牌和频道 ID"
    echo -e "使用命令：nano config.yaml"
    exit 1
fi

# 创建监控脚本
echo -e "\n${YELLOW}6. 创建监控脚本...${NC}"
cat > monitor.sh << 'EOF'
#!/bin/bash

# 获取脚本所在目录的绝对路径
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# 日志函数
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a logs/monitor.log
}

# 确保日志目录存在
mkdir -p logs
chmod 755 logs

# 确保数据目录和文件存在且有正确的权限
mkdir -p data
chmod 755 data
if [ ! -f "data/monitored_items.json" ]; then
    echo '[]' > data/monitored_items.json
fi
chmod 644 data/monitored_items.json

log "启动监控脚本"
log "工作目录: $PWD"

# 检查虚拟环境
if [ ! -d "venv" ]; then
    log "错误: 虚拟环境不存在"
    exit 1
fi

# 检查配置文件
if [ ! -f "config.yaml" ]; then
    log "错误: 配置文件不存在"
    exit 1
fi

# 激活虚拟环境
log "激活虚拟环境"
source venv/bin/activate
if [ $? -ne 0 ]; then
    log "错误: 无法激活虚拟环境"
    exit 1
fi

# 检查Python可执行文件
which python
if [ $? -ne 0 ]; then
    log "错误: Python不可用"
    exit 1
fi

log "Python版本: $(python --version)"
log "pip版本: $(pip --version)"

# 检查依赖
log "检查依赖..."
pip freeze > logs/requirements_installed.txt
if ! pip freeze | grep -q "discord.py"; then
    log "错误: 关键依赖 discord.py 未安装"
    exit 1
fi

# 检查数据文件格式
log "检查数据文件格式..."
if ! python -m json.tool data/monitored_items.json > /dev/null 2>&1; then
    log "警告: 数据文件格式错误，重置为空列表"
    echo '[]' > data/monitored_items.json
fi

# 运行Python程序
while true; do
    log "启动 Python 程序..."
    
    # 将Python程序的输出也记录到日志文件
    python main.py 2>&1 | tee -a logs/app.log
    EXIT_CODE=${PIPESTATUS[0]}
    
    log "程序退出，退出码: $EXIT_CODE"
    
    # 如果是正常退出（退出码为0），则不重启
    if [ $EXIT_CODE -eq 0 ]; then
        log "程序正常退出，不重启"
        break
    fi
    
    # 记录错误信息
    log "程序异常退出，最后100行日志："
    tail -n 100 logs/app.log >> logs/monitor.log
    
    log "5秒后重启..."
    sleep 5
done
EOF

chmod +x monitor.sh

# 设置系统服务
echo -e "\n${YELLOW}7. 设置系统服务...${NC}"
SERVICE_FILE="/etc/systemd/system/popmart-watch.service"

# 检查是否有权限写入服务文件
if ! sudo touch "$SERVICE_FILE" 2>/dev/null; then
    echo -e "${RED}错误：没有权限创建系统服务，请确保有 sudo 权限${NC}"
    exit 1
fi

# 创建服务文件
sudo tee "$SERVICE_FILE" << EOF
[Unit]
Description=POP MART Watch Bot
After=network.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=$USER
WorkingDirectory=$PWD
ExecStart=$PWD/monitor.sh
Restart=always
RestartSec=10
StandardOutput=append:$PWD/logs/service.log
StandardError=append:$PWD/logs/service.log

# 内存限制（1GB）
MemoryLimit=1G

# CPU限制（最多使用50%CPU）
CPUQuota=50%

# 自动重启策略
StartLimitBurst=0
RestartPreventExitStatus=0

[Install]
WantedBy=multi-user.target
EOF

# 设置日志文件权限
touch logs/service.log
chmod 644 logs/service.log

# 重载服务配置
echo -e "\n${YELLOW}8. 启动服务...${NC}"
sudo systemctl daemon-reload
sudo systemctl enable popmart-watch
sudo systemctl restart popmart-watch

# 检查服务状态
echo -e "\n${YELLOW}9. 检查服务状态...${NC}"
sudo systemctl status popmart-watch

echo -e "\n${GREEN}部署完成！${NC}"
echo -e "\n使用以下命令管理服务："
echo -e "${YELLOW}查看服务状态：${NC}sudo systemctl status popmart-watch"
echo -e "${YELLOW}查看服务日志：${NC}sudo journalctl -u popmart-watch -f"
echo -e "${YELLOW}查看程序日志：${NC}tail -f logs/service.log"
echo -e "${YELLOW}重启服务：${NC}sudo systemctl restart popmart-watch"
echo -e "${YELLOW}停止服务：${NC}sudo systemctl stop popmart-watch" 