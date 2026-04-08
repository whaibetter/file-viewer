"""
Session 管理模块
"""

import time
import secrets
from typing import Optional
from flask import request

from .config import SESSION_TIMEOUT

# Session 存储
sessions = {}


def cleanup_sessions():
    """清理过期会话"""
    now = int(time.time())
    expired = [sid for sid, sess in sessions.items() if sess["expire"] < now]
    for sid in expired:
        del sessions[sid]


def create_session(user: str) -> str:
    """创建新会话"""
    cleanup_sessions()
    sid = secrets.token_urlsafe(32)
    sessions[sid] = {"user": user, "expire": int(time.time()) + SESSION_TIMEOUT}
    return sid


def get_session(sid: str) -> Optional[dict]:
    """获取会话"""
    cleanup_sessions()
    sess = sessions.get(sid)
    if sess and sess["expire"] >= int(time.time()):
        return sess
    return None


def delete_session(sid: str):
    """删除会话"""
    sessions.pop(sid, None)


def get_cookie(name: str) -> Optional[str]:
    """获取 cookie"""
    cookies = request.headers.get('Cookie', '')
    for cookie in cookies.split(';'):
        if '=' in cookie:
            k, v = cookie.strip().split('=', 1)
            if k == name:
                return v
    return None


def require_auth() -> Optional[str]:
    """验证登录状态"""
    sid = get_cookie('sessionid')
    if not sid or not get_session(sid):
        return None
    return sid


def is_authenticated() -> bool:
    """检查是否已认证"""
    sid = get_cookie('sessionid')
    return bool(sid and get_session(sid))