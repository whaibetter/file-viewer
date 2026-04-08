# -*- coding: utf-8 -*-
"""
配置管理模块
"""

import os
import yaml
from pathlib import Path
from typing import Optional

# 外部引用
PROJECT_DIR = Path(__file__).parent.parent
PROJECT_CONFIG_FILE = PROJECT_DIR / "config.yaml"

# 全局配置对象
_config = None
_config_file_path = None
_user_config = None
USER_CONFIG_FILE: Optional[Path] = None


def load_config() -> dict:
    """加载 YAML 配置文件"""
    global _config, _config_file_path
    config_path = PROJECT_CONFIG_FILE

    if config_path.exists():
        try:
            with config_path.open("r", encoding="utf-8") as f:
                _config = yaml.safe_load(f) or {}
                _config_file_path = config_path
                return _config
        except Exception as e:
            print(f"Warning: Failed to load config from {config_path}: {e}")

    _config = {}
    return _config


def save_config(config: dict = None) -> bool:
    """保存完整配置到文件"""
    global _config
    if config:
        _config = config
    try:
        config_path = _config_file_path or PROJECT_CONFIG_FILE
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with config_path.open("w", encoding="utf-8") as f:
            yaml.dump(_config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        return True
    except Exception as e:
        print(f"Failed to save config: {e}")
        return False


def get_config() -> dict:
    """获取当前配置"""
    global _config
    if _config is None:
        load_config()
    return _config


def init_user_config_file():
    """初始化用户配置文件路径"""
    global _config, USER_CONFIG_FILE
    _storage_cfg = _config.get("storage", {}) if _config else {}
    _user_config_path = _storage_cfg.get("user_config_file", "/etc/file-viewer/user_config.yaml")
    USER_CONFIG_FILE = Path(_user_config_path)


def load_user_config() -> dict:
    """加载用户配置文件"""
    global _user_config, USER_CONFIG_FILE

    # 确保已初始化用户配置文件路径
    if USER_CONFIG_FILE is None:
        init_user_config_file()

    if USER_CONFIG_FILE.exists():
        try:
            with USER_CONFIG_FILE.open("r", encoding="utf-8") as f:
                _user_config = yaml.safe_load(f) or {}
                return _user_config
        except Exception as e:
            print(f"Warning: Failed to load user config: {e}")
    _user_config = {}
    return _user_config


def save_user_config(config: dict) -> bool:
    """保存用户配置文件"""
    global _user_config, USER_CONFIG_FILE
    try:
        USER_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with USER_CONFIG_FILE.open("w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        _user_config = config
        return True
    except Exception as e:
        print(f"Failed to save user config: {e}")
        return False


def get_user_config() -> dict:
    """获取用户配置"""
    global _user_config
    if _user_config is None:
        load_user_config()
    return _user_config


def get_effective_config() -> dict:
    """获取有效配置（用户配置优先，回退到主配置）"""
    global _config
    user_cfg = get_user_config()

    _server_cfg = _config.get("server", {}) if _config else {}
    _permissions_cfg = _config.get("permissions", {}) if _config else {}
    _download_cfg = _config.get("download_limits", {}) if _config else {}

    # 会话超时
    session_timeout = user_cfg.get("session_timeout", _server_cfg.get("session_timeout", 3600))

    # 默认权限
    default_perms = user_cfg.get("default_permissions", _permissions_cfg.get("default_permissions", {"read": True, "write": True}))

    # 下载限制
    user_dl = user_cfg.get("download_limits", {})
    download_limits = {
        "max_single_file_size": user_dl.get("max_single_file_size", _download_cfg.get("max_single_file_size", 100 * 1024 * 1024)),
        "max_total_download_size": user_dl.get("max_total_download_size", _download_cfg.get("max_total_download_size", 200 * 1024 * 1024)),
        "max_files_in_zip": user_dl.get("max_files_in_zip", _download_cfg.get("max_files_in_zip", 500)),
        "max_dir_depth": user_dl.get("max_dir_depth", _download_cfg.get("max_dir_depth", 20)),
        "max_file_preview_size": user_dl.get("max_file_preview_size", _download_cfg.get("max_file_preview_size", 2 * 1024 * 1024)),
    }

    return {
        "session_timeout": session_timeout,
        "default_permissions": default_perms,
        "download_limits": download_limits
    }


def get_server_config() -> dict:
    """获取服务器配置"""
    global _config
    if _config is None:
        load_config()
    return _config.get("server", {})


def get_storage_config() -> dict:
    """获取存储配置"""
    global _config
    if _config is None:
        load_config()
    return _config.get("storage", {})


def get_security_config() -> dict:
    """获取安全配置"""
    global _config
    if _config is None:
        load_config()
    return _config.get("security", {})


def get_permissions_config() -> dict:
    """获取权限配置"""
    global _config
    if _config is None:
        load_config()
    return _config.get("permissions", {})


def get_download_limits() -> dict:
    """获取下载限制配置"""
    global _config
    if _config is None:
        load_config()
    return _config.get("download_limits", {})


def get_data_dir() -> Path:
    """获取数据存储目录"""
    global _config, _config_file_path
    _storage_cfg = get_storage_config()
    _data_dir_config = _storage_cfg.get("data_dir", "/etc/file-viewer")
    return Path(_data_dir_config) if Path(_data_dir_config).is_absolute() else \
           (_config_file_path.parent / _data_dir_config) if _config_file_path else Path(_data_dir_config)


# 初始化：加载配置并设置用户配置文件路径
load_config()
init_user_config_file()
load_user_config()

# 从配置文件读取设置
_server_cfg = get_server_config()
_storage_cfg = get_storage_config()
_security_cfg = get_security_config()
_permissions_cfg = get_permissions_config()
_download_cfg = get_download_limits()

# 服务器配置
SERVER_HOST = _server_cfg.get("host", "127.0.0.1")
SERVER_PORT = _server_cfg.get("port", 9001)

# 数据目录
DATA_DIR = get_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 数据文件路径
PASSWORD_FILE = DATA_DIR / "passwd"
QUICK_PATHS_FILE = DATA_DIR / "quick_paths.json"

# 获取有效运行时配置
_effective_cfg = get_effective_config()
SESSION_TIMEOUT = _effective_cfg["session_timeout"]
DEFAULT_PERMISSIONS = _effective_cfg["default_permissions"]
_download_limits = _effective_cfg["download_limits"]
MAX_SINGLE_FILE_SIZE = _download_limits["max_single_file_size"]
MAX_TOTAL_DOWNLOAD_SIZE = _download_limits["max_total_download_size"]
MAX_FILES_IN_ZIP = _download_limits["max_files_in_zip"]
MAX_DIR_DEPTH = _download_limits["max_dir_depth"]
MAX_FILE_PREVIEW_SIZE = _download_limits["max_file_preview_size"]

# 文件夹权限配置（不在用户配置中，仅从主配置读取）
FOLDER_PERMISSIONS = _permissions_cfg.get("folder_permissions") or {}