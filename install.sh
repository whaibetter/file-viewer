#!/bin/bash
# file-viewer 安装脚本
# 用法: sudo ./install.sh

set -e

BOLD='\033[1m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[0;33m'
RESET='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${BOLD}=== File Viewer 安装程序 ===${RESET}"

# 检查 root 权限
if [ "$EUID" -ne 0 ]; then
    echo -e "${YELLOW}请使用 sudo 运行此脚本${RESET}"
    exit 1
fi

# 1. 复制后端服务
echo -e "${CYAN}[1/5] 安装后端服务...${RESET}"
cp "$SCRIPT_DIR/file-viewer-server.py" /usr/local/bin/
chmod 644 /usr/local/bin/file-viewer-server.py

# 2. 复制管理脚本
echo -e "${CYAN}[2/5] 安装管理脚本...${RESET}"
cp "$SCRIPT_DIR/file-viewer" /usr/local/bin/
chmod 755 /usr/local/bin/file-viewer

# 3. 安装 systemd 服务
echo -e "${CYAN}[3/5] 安装 systemd 服务...${RESET}"
cp "$SCRIPT_DIR/file-viewer.service" /etc/systemd/system/
systemctl daemon-reload

# 4. 复制前端页面
echo -e "${CYAN}[4/5] 安装前端页面...${RESET}"
mkdir -p /var/www/html
cp "$SCRIPT_DIR/index.html" /var/www/html/
chmod 644 /var/www/html/index.html

# 5. 创建密码文件（如果不存在）
echo -e "${CYAN}[5/5] 初始化密码文件...${RESET}"
if [ ! -f /etc/file-viewer.passwd ]; then
    # 默认密码: admin
    echo -n "admin" | sha256sum | awk '{print $1}' > /etc/file-viewer.passwd
    chmod 600 /etc/file-viewer.passwd
    echo -e "${YELLOW}已创建默认密码文件，默认密码: admin${RESET}"
    echo -e "${YELLOW}请运行 'file-viewer passwd' 修改密码${RESET}"
else
    echo -e "密码文件已存在，跳过"
fi

# 启用并启动服务
echo ""
echo -e "${CYAN}启用服务...${RESET}"
systemctl enable file-viewer
systemctl start file-viewer

echo ""
echo -e "${GREEN}${BOLD}安装完成！${RESET}"
echo ""
echo -e "访问地址: ${CYAN}http://$(hostname -I | awk '{print $1}')${RESET}"
echo -e "默认密码: ${CYAN}admin${RESET} (请及时修改)"
echo ""
echo -e "管理命令:"
echo -e "  ${CYAN}file-viewer start${RESET}    启动服务"
echo -e "  ${CYAN}file-viewer stop${RESET}     停止服务"
echo -e "  ${CYAN}file-viewer restart${RESET}  重启服务"
echo -e "  ${CYAN}file-viewer status${RESET}   查看状态"
echo -e "  ${CYAN}file-viewer passwd${RESET}   修改密码"
