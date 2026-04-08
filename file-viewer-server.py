#!/usr/bin/env python3
"""
File Viewer Backend Service with Flask-SocketIO
Supports HTTP API

This file now serves as a compatibility启动脚本.
The main server code has been moved to the 'server' package.
"""

import sys
from pathlib import Path

# 确保可以导入 server 包
sys.path.insert(0, str(Path(__file__).parent))

from server.main import main

if __name__ == '__main__':
    main()