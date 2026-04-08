"""
权限与验证模块
"""

import os
import stat
import pwd
import grp
import hashlib
import hmac
from typing import Optional

from .config import (
    get_security_config,
    get_permissions_config,
    get_effective_config,
    DEFAULT_PERMISSIONS,
    FOLDER_PERMISSIONS,
    PASSWORD_FILE,
    QUICK_PATHS_FILE,
    DATA_DIR,
)


# === 白名单管理 ===
def load_whitelist() -> list:
    """加载删除白名单（从主配置文件）"""
    return get_security_config().get("delete_whitelist", ["/tmp", "/var/tmp"])


def save_whitelist(whitelist: list) -> bool:
    """保存删除白名单（到主配置文件）"""
    from .config import get_config, save_config

    config = get_config()
    if "security" not in config:
        config["security"] = {}
    config["security"]["delete_whitelist"] = whitelist
    return save_config(config)


def is_in_whitelist(path: str) -> bool:
    """检查路径是否在白名单中"""
    whitelist = load_whitelist()
    normalized_path = os.path.normpath(path)
    for allowed_path in whitelist:
        normalized_allowed = os.path.normpath(allowed_path)
        if normalized_path == normalized_allowed:
            return True
        if normalized_path.startswith(normalized_allowed + os.sep):
            return True
    return False


def format_whitelist_with_types(whitelist: list) -> list:
    """为白名单添加类型信息"""
    result = []
    for p in whitelist:
        normalized = os.path.normpath(p)
        if os.path.exists(normalized):
            path_type = "file" if os.path.isfile(normalized) else "dir"
        else:
            path_type = "unknown"
        result.append({"path": p, "type": path_type})
    return result


# === 快捷路径管理 ===
def get_quick_paths() -> list:
    """获取快捷路径配置（从 JSON 文件）"""
    try:
        if QUICK_PATHS_FILE.exists():
            with QUICK_PATHS_FILE.open("r", encoding="utf-8") as f:
                return __import__('json').load(f)
    except:
        pass
    return [
        {"path": "/", "name": "/ 根目录"},
        {"path": "/etc", "name": "/etc"},
        {"path": "/var/log", "name": "/var/log"},
        {"path": "/var/www/html", "name": "/var/www/html"},
    ]


def save_quick_paths(paths: list) -> bool:
    """保存快捷路径配置（到 JSON 文件）"""
    import json
    try:
        QUICK_PATHS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with QUICK_PATHS_FILE.open("w", encoding="utf-8") as f:
            json.dump(paths, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Failed to save quick paths: {e}")
        return False


# === 文件权限 ===
def get_file_permissions(path: str) -> dict:
    """获取文件权限信息"""
    try:
        st = os.stat(path)
        mode = st.st_mode
        try:
            owner = pwd.getpwuid(st.st_uid).pw_name
        except KeyError:
            owner = str(st.st_uid)
        try:
            group = grp.getgrgid(st.st_gid).gr_name
        except KeyError:
            group = str(st.st_gid)
        return {
            "mode": stat.filemode(mode),
            "octal": oct(stat.S_IMODE(mode)),
            "owner": owner,
            "group": group,
            "uid": st.st_uid,
            "gid": st.st_gid,
            "mtime": st.st_mtime,
        }
    except Exception as e:
        return {"error": str(e)}


def get_folder_permission_config(path: str) -> dict:
    """获取文件夹权限配置"""
    best_match = None
    best_len = 0
    for folder_path, perms in FOLDER_PERMISSIONS.items():
        if path.startswith(folder_path) and len(folder_path) > best_len:
            best_match = perms
            best_len = len(folder_path)
    return best_match if best_match else DEFAULT_PERMISSIONS


def check_permission(path: str, action: str) -> tuple:
    """检查权限"""
    perms = get_folder_permission_config(path)
    if action in perms:
        if perms[action] is None or perms[action]:
            return True, "allowed"
        else:
            return False, f"{action} permission denied for this folder"
    else:
        if action == "delete":
            return True, "allowed"
        if action == "read":
            return True, "allowed"
        else:
            return False, f"{action} permission denied by default"


# === 密码验证 ===
def verify_password(password: str) -> bool:
    """验证密码 - 从密码文件读取哈希"""
    try:
        if PASSWORD_FILE.exists():
            with PASSWORD_FILE.open("r") as f:
                stored_hash = f.read().strip()
            return hmac.compare_digest(
                stored_hash,
                hashlib.sha256(password.encode()).hexdigest()
            )
        return False
    except Exception:
        return False


def change_password(old_password: str, new_password: str) -> tuple:
    """修改密码 - 验证旧密码后设置新密码"""
    if not verify_password(old_password):
        return False, "旧密码错误"
    if not new_password or len(new_password) < 4:
        return False, "新密码长度至少4位"
    try:
        new_hash = hashlib.sha256(new_password.encode()).hexdigest()
        PASSWORD_FILE.parent.mkdir(parents=True, exist_ok=True)
        with PASSWORD_FILE.open("w") as f:
            f.write(new_hash)
        os.chmod(PASSWORD_FILE, 0o600)
        return True, "密码修改成功"
    except Exception as e:
        return False, f"修改失败: {e}"