# -*- coding: utf-8 -*-
"""
File Viewer Server - Modular Package
"""

import os
from pathlib import Path
from flask import Flask
from flask_socketio import SocketIO

# 项目根目录
PROJECT_DIR = Path(__file__).parent.parent
PROJECT_CONFIG_FILE = PROJECT_DIR / "config.yaml"

# 全局配置对象
_config = None
_config_file_path = None

# Flask 应用
app = None
socketio = None


def create_app() -> Flask:
    """创建并配置Flask应用"""
    global app, socketio, _config, _config_file_path

    # 加载配置
    from .config import load_config, load_user_config
    _config = load_config()
    load_user_config()

    # 创建Flask应用
    app = Flask(__name__, static_folder=None)
    app.config['SECRET_KEY'] = os.urandom(32)
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

    # 注册路由蓝图
    from .routes import register_routes
    register_routes(app)

    return app


def get_app() -> Flask:
    """获取Flask应用实例"""
    global app
    if app is None:
        create_app()
    return app


def get_socketio() -> SocketIO:
    """获取SocketIO实例"""
    global socketio
    if socketio is None:
        get_app()  # 确保已初始化
    return socketio