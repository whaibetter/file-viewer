"""
路由注册模块
"""

from .files import files_bp
from .config import config_bp
from .whitelist import whitelist_bp
from .ai import ai_bp


def register_routes(app):
    """注册所有路由蓝图"""
    app.register_blueprint(files_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(whitelist_bp)
    app.register_blueprint(ai_bp)