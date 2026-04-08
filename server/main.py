# -*- coding: utf-8 -*-
"""
启动入口
"""

from . import create_app, get_socketio
from .config import SERVER_HOST, SERVER_PORT


def main():
    """启动服务器"""
    print(f"Starting File Viewer Server on http://{SERVER_HOST}:{SERVER_PORT}")
    app = create_app()
    socketio = get_socketio()
    socketio.run(app, host=SERVER_HOST, port=SERVER_PORT, debug=False, allow_unsafe_werkzeug=True)


if __name__ == '__main__':
    main()