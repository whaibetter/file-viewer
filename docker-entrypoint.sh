#!/bin/bash
set -e

DATA_DIR="${CLOUDREIN_DATA_DIR:-/etc/cloudrein}"

# 初始化数据目录
mkdir -p "$DATA_DIR"

# 初始化密码文件（默认密码: admin）
if [ ! -f "$DATA_DIR/passwd" ]; then
    echo -n "admin" | sha256sum | awk '{print $1}' > "$DATA_DIR/passwd"
    chmod 600 "$DATA_DIR/passwd"
    echo "[init] Created default password file (default password: admin)"
fi

# 初始化 AI 配置
if [ ! -f "$DATA_DIR/ai_config.json" ]; then
    cat > "$DATA_DIR/ai_config.json" << 'EOF'
{
    "api_key": "",
    "model": "deepseek-ocr",
    "base_url": "https://api.siliconflow.cn/v1/chat/completions"
}
EOF
    echo "[init] Created AI config file"
fi

# 初始化快捷路径（包含 /host 以便访问宿主机文件）
if [ ! -f "$DATA_DIR/quick_paths.json" ]; then
    cat > "$DATA_DIR/quick_paths.json" << 'EOF'
[
    {"path": "/host", "name": "/host 宿主机"},
    {"path": "/host/home", "name": "/host/home"},
    {"path": "/host/var/log", "name": "/host/var/log"},
    {"path": "/host/var/www/html", "name": "/host/var/www/html"},
    {"path": "/host/tmp", "name": "/host/tmp"}
]
EOF
    echo "[init] Created quick paths config"
fi

exec "$@"
