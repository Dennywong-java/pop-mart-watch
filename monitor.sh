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
