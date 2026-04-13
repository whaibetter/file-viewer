#!/bin/bash
# CloudRein 安装脚本
# 用法: sudo ./install.sh

set -e

BOLD='\033[1m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
RESET='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="/home/cloudrein"
DATA_DIR="/etc/cloudrein"

echo -e "${BOLD}========================================${RESET}"
echo -e "${BOLD}   CloudRein 安装程序 v1.0${RESET}"
echo -e "${BOLD}========================================${RESET}"
echo ""

# 检查 root 权限
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}错误: 请使用 sudo 运行此脚本${RESET}"
    echo "  用法: sudo ./install.sh"
    exit 1
fi

# 前置检查
echo -e "${CYAN}[检查] 验证安装环境...${RESET}"

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}错误: 未找到 Python 3，请先安装 Python 3.8+${RESET}"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo -e "  Python 版本: ${GREEN}${PYTHON_VERSION}${RESET}"

# 检查 pip
if ! command -v pip3 &> /dev/null && ! command -v pip &> /dev/null; then
    echo -e "${RED}错误: 未找到 pip，请先安装 python3-pip${RESET}"
    exit 1
fi

# 检查 systemd
if ! command -v systemctl &> /dev/null; then
    echo -e "${RED}错误: 未找到 systemd，本脚本仅支持 systemd 系统${RESET}"
    exit 1
fi

echo -e "  系统检查: ${GREEN}通过${RESET}"
echo ""

# 1. 安装 Python 依赖
echo -e "${CYAN}[1/5] 安装 Python 依赖...${RESET}"
PIP_CMD="pip3"
if ! command -v pip3 &> /dev/null; then
    PIP_CMD="pip"
fi

$PIP_CMD install -q --upgrade pyyaml flask flask-socketio python-socketio eventlet aiohttp python-dotenv 2>/dev/null
echo -e "  依赖安装: ${GREEN}完成${RESET}"
echo ""

# 2. 创建数据目录
echo -e "${CYAN}[2/5] 创建数据目录...${RESET}"
mkdir -p "$DATA_DIR"
chmod 755 "$DATA_DIR"
echo -e "  数据目录: ${GREEN}${DATA_DIR}${RESET}"
echo ""

# 3. 初始化密码文件
echo -e "${CYAN}[3/5] 初始化密码文件...${RESET}"
if [ ! -f "$DATA_DIR/passwd" ]; then
    # 默认密码: admin
    echo -n "admin" | sha256sum | awk '{print $1}' > "$DATA_DIR/passwd"
    chmod 600 "$DATA_DIR/passwd"
    echo -e "  ${YELLOW}已创建默认密码文件，默认密码: admin${RESET}"
    echo -e "  ${YELLOW}请运行 'cloudrein passwd' 修改密码${RESET}"
else
    echo -e "  密码文件已存在，跳过"
fi
echo ""

# 4. 初始化 AI 配置文件
echo -e "${CYAN}[4/5] 初始化配置文件...${RESET}"
if [ ! -f "$DATA_DIR/ai_config.json" ]; then
    cat > "$DATA_DIR/ai_config.json" << 'EOF'
{
    "api_key": "",
    "model": "deepseek-ocr",
    "base_url": "https://api.siliconflow.cn/v1/chat/completions"
}
EOF
    chmod 644 "$DATA_DIR/ai_config.json"
    echo -e "  已创建 AI 配置文件: ${GREEN}${DATA_DIR}/ai_config.json${RESET}"
else
    echo -e "  AI 配置文件已存在，跳过"
fi

# 初始化快捷路径配置
if [ ! -f "$DATA_DIR/quick_paths.json" ]; then
    cat > "$DATA_DIR/quick_paths.json" << 'EOF'
[
    {"path": "/", "name": "/ 根目录"},
    {"path": "/etc", "name": "/etc"},
    {"path": "/var/log", "name": "/var/log"},
    {"path": "/var/www/html", "name": "/var/www/html"}
]
EOF
    chmod 644 "$DATA_DIR/quick_paths.json"
    echo -e "  已创建快捷路径配置: ${GREEN}${DATA_DIR}/quick_paths.json${RESET}"
else
    echo -e "  快捷路径配置已存在，跳过"
fi
echo ""

# 5. 安装管理脚本和 systemd 服务
echo -e "${CYAN}[5/5] 安装服务...${RESET}"

# 安装管理脚本
cp "$SCRIPT_DIR/cloudrein" /usr/local/bin/
chmod 755 /usr/local/bin/cloudrein
echo -e "  管理脚本: ${GREEN}/usr/local/bin/cloudrein${RESET}"

# 更新 systemd 服务文件中的项目路径
SERVICE_FILE="$SCRIPT_DIR/cloudrein.service"
if [ -f "$SERVICE_FILE" ]; then
    # 替换 WorkingDirectory 为实际项目路径
    sed "s|WorkingDirectory=.*|WorkingDirectory=${PROJECT_DIR}|" "$SERVICE_FILE" > /tmp/cloudrein.service.tmp
    cp /tmp/cloudrein.service.tmp /etc/systemd/system/cloudrein.service
    rm -f /tmp/cloudrein.service.tmp
    chmod 644 /etc/systemd/system/cloudrein.service
    echo -e "  systemd 服务: ${GREEN}/etc/systemd/system/cloudrein.service${RESET}"
else
    echo -e "  ${RED}警告: 未找到 cloudrein.service 文件${RESET}"
fi

systemctl daemon-reload
echo ""

# 启用并启动服务
echo -e "${CYAN}启动 CloudRein 服务...${RESET}"
systemctl enable cloudrein
systemctl restart cloudrein

# 检查服务状态
sleep 2
if systemctl is-active --quiet cloudrein; then
    echo -e "  服务状态: ${GREEN}运行中${RESET}"
else
    echo -e "  服务状态: ${RED}未运行${RESET}"
    echo -e "  ${YELLOW}请运行 'journalctl -u cloudrein -n 20' 查看日志${RESET}"
fi

echo ""
echo -e "${GREEN}${BOLD}========================================${RESET}"
echo -e "${GREEN}${BOLD}   安装完成！${RESET}"
echo -e "${GREEN}${BOLD}========================================${RESET}"
echo ""
echo -e "项目目录:   ${CYAN}${PROJECT_DIR}${RESET}"
echo -e "数据目录:   ${CYAN}${DATA_DIR}${RESET}"
echo -e "访问地址:   ${CYAN}http://$(hostname -I | awk '{print $1}'):9001${RESET}"
echo -e "默认密码:   ${CYAN}admin${RESET} ${YELLOW}(请及时修改)${RESET}"
echo ""
echo -e "${BOLD}管理命令:${RESET}"
echo -e "  ${CYAN}cloudrein start${RESET}     启动服务"
echo -e "  ${CYAN}cloudrein stop${RESET}      停止服务"
echo -e "  ${CYAN}cloudrein restart${RESET}   重启服务 (加载最新代码)"
echo -e "  ${CYAN}cloudrein status${RESET}    查看状态"
echo -e "  ${CYAN}cloudrein logs${RESET}      查看日志"
echo -e "  ${CYAN}cloudrein logs -f${RESET}   实时查看日志"
echo -e "  ${CYAN}cloudrein enable${RESET}    设置开机自启"
echo -e "  ${CYAN}cloudrein disable${RESET}   取消开机自启"
echo -e "  ${CYAN}cloudrein passwd${RESET}    修改密码"
echo ""
echo -e "${BOLD}提示:${RESET}"
echo -e "  服务直接运行项目目录中的代码"
echo -e "  修改 index.html 或 cloudrein-server.py 后"
echo -e "  运行 ${CYAN}cloudrein restart${RESET} 即可生效"
echo ""
echo -e "${BOLD}下一步:${RESET}"
echo -e "  1. 运行 ${CYAN}cloudrein passwd${RESET} 修改默认密码"
echo -e "  2. 访问 ${CYAN}http://<服务器IP>:9001${RESET} 登录系统"
echo -e "  3. 配置 Nginx 反向代理以启用 HTTPS (推荐)"
echo -e "  4. 在设置页面配置删除白名单和快捷路径"
echo ""
