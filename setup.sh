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

# 创建必要的目录
echo -e "\n${YELLOW}1. 创建必要的目录...${NC}"
mkdir -p logs data

# 创建并激活虚拟环境
echo -e "\n${YELLOW}2. 设置Python虚拟环境...${NC}"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate

# 安装依赖
echo -e "\n${YELLOW}3. 安装Python依赖...${NC}"
pip install -r requirements.txt

# 配置文件检查
echo -e "\n${YELLOW}4. 检查配置文件...${NC}"
if [ ! -f "config.yaml" ]; then
    echo -e "${RED}请注意：需要创建并配置 config.yaml 文件${NC}"
    cp config.example.yaml config.yaml
    echo -e "请编辑 config.yaml 文件，设置您的 Discord 令牌和频道 ID"
    echo -e "使用命令：nano config.yaml"
    exit 1
fi

# 创建监控脚本
echo -e "\n${YELLOW}5. 创建监控脚本...${NC}"
cat > monitor.sh << 'EOF'
#!/bin/bash

# 获取脚本所在目录的绝对路径
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# 激活虚拟环境
source venv/bin/activate

# 运行Python程序
while true; do
    echo "[$(date)] 启动程序..."
    python main.py
    
    EXIT_CODE=$?
    echo "[$(date)] 程序退出，退出码: $EXIT_CODE"
    
    # 如果是正常退出（退出码为0），则不重启
    if [ $EXIT_CODE -eq 0 ]; then
        echo "[$(date)] 程序正常退出，不重启"
        break
    fi
    
    echo "[$(date)] 程序异常退出，5秒后重启..."
    sleep 5
done
EOF

chmod +x monitor.sh

# 设置系统服务
echo -e "\n${YELLOW}6. 设置系统服务...${NC}"
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

# 重载服务配置
echo -e "\n${YELLOW}7. 启动服务...${NC}"
sudo systemctl daemon-reload
sudo systemctl enable popmart-watch
sudo systemctl restart popmart-watch

# 检查服务状态
echo -e "\n${YELLOW}8. 检查服务状态...${NC}"
sudo systemctl status popmart-watch

echo -e "\n${GREEN}部署完成！${NC}"
echo -e "\n使用以下命令管理服务："
echo -e "${YELLOW}查看服务状态：${NC}sudo systemctl status popmart-watch"
echo -e "${YELLOW}查看服务日志：${NC}sudo journalctl -u popmart-watch -f"
echo -e "${YELLOW}查看程序日志：${NC}tail -f logs/service.log"
echo -e "${YELLOW}重启服务：${NC}sudo systemctl restart popmart-watch"
echo -e "${YELLOW}停止服务：${NC}sudo systemctl stop popmart-watch" 