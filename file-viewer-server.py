#!/usr/bin/env python3
"""
File Viewer Backend Service with Flask-SocketIO
Supports HTTP API
"""

import json
import os
import stat
import hashlib
import time
import secrets
import hmac
import subprocess
import re
import pwd
import grp
import zipfile
import io
import shutil
import yaml
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_socketio import SocketIO

# === 配置文件路径 ===
PROJECT_DIR = Path("/home/file-viewer")
PROJECT_CONFIG_FILE = PROJECT_DIR / "config.yaml"

# 全局配置对象
_config = None
_config_file_path = None
_user_config = None
USER_CONFIG_FILE = None  # 将在加载主配置后初始化


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


# 加载主配置
load_config()

# === 初始化用户配置文件路径 ===
_storage_cfg = _config.get("storage", {})
_user_config_path = _storage_cfg.get("user_config_file", "/etc/file-viewer/user_config.yaml")
USER_CONFIG_FILE = Path(_user_config_path)


# === 用户配置管理 ===
def load_user_config() -> dict:
    """加载用户配置文件"""
    global _user_config
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
    global _user_config
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


# 加载配置
load_config()
load_user_config()

# === 从配置文件读取设置 ===
_server_cfg = _config.get("server", {})
_storage_cfg = _config.get("storage", {})
_security_cfg = _config.get("security", {})
_ui_cfg = _config.get("ui", {})
_permissions_cfg = _config.get("permissions", {})
_download_cfg = _config.get("download_limits", {})

# 服务器配置
SERVER_HOST = _server_cfg.get("host", "127.0.0.1")
SERVER_PORT = _server_cfg.get("port", 9001)

# === 数据存储目录配置 ===
_data_dir_config = _storage_cfg.get("data_dir", "/etc/file-viewer")
DATA_DIR = Path(_data_dir_config) if Path(_data_dir_config).is_absolute() else (_config_file_path.parent / _data_dir_config) if _config_file_path else Path(_data_dir_config)

DATA_DIR.mkdir(parents=True, exist_ok=True)

# 数据文件路径
PASSWORD_FILE = DATA_DIR / "passwd"
QUICK_PATHS_FILE = DATA_DIR / "quick_paths.json"


def get_effective_config() -> dict:
    """获取有效配置（用户配置优先，回退到主配置）"""
    user_cfg = get_user_config()
    
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

# === Flask 应用 ===
app = Flask(__name__, static_folder=None)
app.config['SECRET_KEY'] = secrets.token_hex(32)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# === Session 管理 ===
sessions = {}


def cleanup_sessions():
    now = int(time.time())
    expired = [sid for sid, sess in sessions.items() if sess["expire"] < now]
    for sid in expired:
        del sessions[sid]


def create_session(user: str) -> str:
    cleanup_sessions()
    sid = secrets.token_urlsafe(32)
    sessions[sid] = {"user": user, "expire": int(time.time()) + SESSION_TIMEOUT}
    return sid


def get_session(sid: str):
    cleanup_sessions()
    sess = sessions.get(sid)
    if sess and sess["expire"] >= int(time.time()):
        return sess
    return None


def delete_session(sid: str):
    sessions.pop(sid, None)


def get_cookie(name: str):
    """获取 cookie"""
    cookies = request.headers.get('Cookie', '')
    for cookie in cookies.split(';'):
        if '=' in cookie:
            k, v = cookie.strip().split('=', 1)
            if k == name:
                return v
    return None


def require_auth():
    """验证登录状态"""
    sid = get_cookie('sessionid')
    if not sid or not get_session(sid):
        return None
    return sid


# === 配置管理函数 ===
def load_whitelist() -> list:
    """加载删除白名单（从主配置文件）"""
    return _security_cfg.get("delete_whitelist", ["/tmp", "/var/tmp"])


def save_whitelist(whitelist: list) -> bool:
    """保存删除白名单（到主配置文件）"""
    global _config, _security_cfg
    if "security" not in _config:
        _config["security"] = {}
    _config["security"]["delete_whitelist"] = whitelist
    _security_cfg["delete_whitelist"] = whitelist
    return save_config()


def get_quick_paths() -> list:
    """获取快捷路径配置（从 JSON 文件）"""
    try:
        if QUICK_PATHS_FILE.exists():
            with QUICK_PATHS_FILE.open("r", encoding="utf-8") as f:
                return json.load(f)
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
    try:
        with QUICK_PATHS_FILE.open("w", encoding="utf-8") as f:
            json.dump(paths, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Failed to save quick paths: {e}")
        return False


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


def get_file_permissions(path: str) -> dict:
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
    best_match = None
    best_len = 0
    for folder_path, perms in FOLDER_PERMISSIONS.items():
        if path.startswith(folder_path) and len(folder_path) > best_len:
            best_match = perms
            best_len = len(folder_path)
    return best_match if best_match else DEFAULT_PERMISSIONS


def check_permission(path: str, action: str) -> tuple:
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


# === 系统信息收集 ===
def _read_file(path: str, default: str = "") -> str:
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return default


def _run(cmd: str) -> str:
    try:
        return subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL, timeout=5).decode().strip()
    except Exception:
        return ""


_prev_net = {"time": 0, "rx": 0, "tx": 0}


def collect_system_info() -> dict:
    info = {}
    info["hostname"] = _read_file("/etc/hostname", "unknown")
    info["kernel"] = _read_file("/proc/version").split(" ")[:3]
    info["kernel"] = " ".join(info["kernel"]) if info["kernel"] else ""
    os_release = _read_file("/etc/os-release")
    m = re.search(r'PRETTY_NAME="([^"]+)"', os_release)
    info["os"] = m.group(1) if m else "Linux"
    try:
        uptime_s = float(_read_file("/proc/uptime").split()[0])
        days = int(uptime_s // 86400)
        hours = int((uptime_s % 86400) // 3600)
        mins = int((uptime_s % 3600) // 60)
        parts = []
        if days > 0: parts.append(f"{days}天")
        if hours > 0: parts.append(f"{hours}小时")
        parts.append(f"{mins}分钟")
        info["uptime"] = " ".join(parts)
    except Exception:
        info["uptime"] = "N/A"
    try:
        load = _read_file("/proc/loadavg").split()[:3]
        info["load"] = {"1m": float(load[0]), "5m": float(load[1]), "15m": float(load[2])}
    except Exception:
        info["load"] = {"1m": 0, "5m": 0, "15m": 0}
    try:
        cpuinfo = _read_file("/proc/cpuinfo")
        models = re.findall(r"model name\s*:\s*(.+)", cpuinfo)
        info["cpu"] = {
            "model": models[0].strip() if models else "Unknown",
            "cores": len(models),
            "threads": len(models),
        }
        phys = set(re.findall(r"core id\s*:\s*(\d+)", cpuinfo))
        sockets = set(re.findall(r"physical id\s*:\s*(\d+)", cpuinfo))
        info["cpu"]["physical_cores"] = len(phys) * max(len(sockets), 1) if phys and sockets else info["cpu"]["cores"]
    except Exception:
        info["cpu"] = {"model": "Unknown", "cores": 0, "threads": 0, "physical_cores": 0}
    try:
        with open("/proc/stat") as f:
            line = f.readline()
        vals = list(map(int, line.split()[1:]))
        idle = vals[3] + vals[4]
        total = sum(vals[:8])
        if not hasattr(collect_system_info, "_prev_cpu"):
            collect_system_info._prev_cpu = (idle, total)
            info["cpu"]["usage_percent"] = round(min(info["load"]["1m"] / max(info["cpu"]["cores"], 1) * 100, 100), 1)
        else:
            prev_idle, prev_total = collect_system_info._prev_cpu
            d_idle = idle - prev_idle
            d_total = total - prev_total
            info["cpu"]["usage_percent"] = round((1 - d_idle / d_total) * 100, 1) if d_total > 0 else 0.0
            collect_system_info._prev_cpu = (idle, total)
    except Exception:
        info["cpu"]["usage_percent"] = 0.0
    try:
        meminfo = _read_file("/proc/meminfo")
        mem = {}
        for line in meminfo.splitlines():
            parts = line.split(":")
            if len(parts) == 2:
                mem[parts[0].strip()] = int(parts[1].strip().split()[0])
        total = mem.get("MemTotal", 0)
        available = mem.get("MemAvailable", 0)
        used = total - available
        swap_total = mem.get("SwapTotal", 0)
        swap_free = mem.get("SwapFree", 0)
        swap_used = swap_total - swap_free
        info["memory"] = {
            "total": total * 1024, "used": used * 1024, "available": available * 1024,
            "usage_percent": round(used / total * 100, 1) if total > 0 else 0,
            "swap_total": swap_total * 1024, "swap_used": swap_used * 1024,
            "swap_percent": round(swap_used / swap_total * 100, 1) if swap_total > 0 else 0,
            "buffers": mem.get("Buffers", 0) * 1024, "cached": mem.get("Cached", 0) * 1024,
        }
    except Exception:
        info["memory"] = {"total": 0, "used": 0, "available": 0, "usage_percent": 0, "swap_total": 0, "swap_used": 0, "swap_percent": 0, "buffers": 0, "cached": 0}
    try:
        df_out = _run("df -B1 -x tmpfs -x devtmpfs -x squashfs -x overlay 2>/dev/null")
        disks = []
        for line in df_out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 6 and parts[0].startswith("/"):
                total_b = int(parts[1])
                used_b = int(parts[2])
                avail_b = int(parts[3])
                disks.append({"device": parts[0], "mount": parts[5], "total": total_b, "used": used_b, "available": avail_b, "usage_percent": round(used_b / total_b * 100, 1) if total_b > 0 else 0})
        info["disks"] = disks
    except Exception:
        info["disks"] = []
    try:
        net_dev = _read_file("/proc/net/dev")
        interfaces = []
        total_rx, total_tx = 0, 0
        for line in net_dev.splitlines()[2:]:
            parts = line.split()
            if len(parts) >= 10:
                name = parts[0].rstrip(":")
                if name == "lo":
                    continue
                rx = int(parts[1])
                tx = int(parts[9])
                total_rx += rx
                total_tx += tx
                ip = _run(f"ip -4 addr show {name} 2>/dev/null | grep -oP 'inet \\K[\\d.]+'")
                interfaces.append({"name": name, "ip": ip or "-", "rx_bytes": rx, "tx_bytes": tx})
        now = time.time()
        global _prev_net
        dt = now - _prev_net["time"] if _prev_net["time"] > 0 else 0
        rx_rate = (total_rx - _prev_net["rx"]) / dt if dt > 0 else 0
        tx_rate = (total_tx - _prev_net["tx"]) / dt if dt > 0 else 0
        _prev_net = {"time": now, "rx": total_rx, "tx": total_tx}
        info["network"] = {"interfaces": interfaces, "rx_rate": max(0, rx_rate), "tx_rate": max(0, tx_rate)}
    except Exception:
        info["network"] = {"interfaces": [], "rx_rate": 0, "tx_rate": 0}
    try:
        ps_out = _run("ps aux --sort=-%cpu 2>/dev/null | head -11")
        procs = []
        for line in ps_out.splitlines()[1:]:
            parts = line.split(None, 10)
            if len(parts) >= 11:
                procs.append({"user": parts[0], "pid": int(parts[1]), "cpu": float(parts[2]), "mem": float(parts[3]), "command": parts[10][:80]})
        info["processes"] = procs
    except Exception:
        info["processes"] = []
    try:
        for tp in ["/sys/class/thermal/thermal_zone0/temp", "/sys/class/hwmon/hwmon0/temp1_input"]:
            raw = _read_file(tp)
            if raw:
                info["temperature"] = round(int(raw) / 1000, 1)
                break
        else:
            info["temperature"] = None
    except Exception:
        info["temperature"] = None
    info["timestamp"] = int(time.time())
    return info


def get_dir_size_and_count(path: str) -> tuple:
    """计算目录总大小和文件数量"""
    total_size = 0
    file_count = 0
    try:
        for root, dirs, files in os.walk(path):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    total_size += os.path.getsize(fp)
                    file_count += 1
                    if file_count > MAX_FILES_IN_ZIP or total_size > MAX_TOTAL_DOWNLOAD_SIZE:
                        return total_size, file_count
                except OSError:
                    pass
    except OSError:
        pass
    return total_size, file_count





# === HTTP 路由 ===
@app.route('/')
@app.route('/index.html')
def index():
    index_path = PROJECT_DIR / 'index.html'
    if index_path.exists():
        with open(index_path, 'r', encoding='utf-8') as f:
            return f.read(), 200, {'Content-Type': 'text/html; charset=utf-8'}
    return jsonify({'error': 'index.html not found'}), 404


@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.json
        password = data.get('password', '')
        if verify_password(password):
            sid = create_session('admin')
            response = jsonify({'success': True})
            response.set_cookie('sessionid', sid, max_age=SESSION_TIMEOUT, httponly=True, samesite='Lax')
            return response
        else:
            return jsonify({'error': 'Invalid password'}), 401
    except Exception as e:
        return jsonify({'error': 'Bad request'}), 400


@app.route('/api/logout', methods=['POST'])
def logout():
    sid = get_cookie('sessionid')
    if sid:
        delete_session(sid)
    response = jsonify({'success': True})
    response.set_cookie('sessionid', '', max_age=0)
    return response


@app.route('/api/auth/check', methods=['GET'])
def auth_check():
    sid = get_cookie('sessionid')
    return jsonify({'authenticated': bool(get_session(sid))})


@app.route('/api/system', methods=['GET'])
def system():
    if not require_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify(collect_system_info())


@app.route('/api/file', methods=['GET'])
def file_info():
    if not require_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    path = request.args.get('path', '')
    if not path:
        return jsonify({'error': "Missing 'path' parameter"}), 400

    file_path = os.path.normpath(path)
    if not os.path.exists(file_path):
        return jsonify({'error': f'File not found: {file_path}'}), 404

    allowed, reason = check_permission(file_path, 'read')
    if not allowed:
        return jsonify({'error': reason}), 403

    folder_perms = get_folder_permission_config(file_path)

    if os.path.isdir(file_path):
        try:
            entries = []
            for name in sorted(os.listdir(file_path)):
                full = os.path.join(file_path, name)
                entries.append({
                    'name': name,
                    'type': 'dir' if os.path.isdir(full) else 'file',
                    'size': os.path.getsize(full) if os.path.isfile(full) else None,
                    'permissions': get_file_permissions(full),
                    'can_delete': is_in_whitelist(full),
                })
            dir_can_delete = is_in_whitelist(file_path)
            return jsonify({
                'type': 'directory',
                'path': file_path,
                'entries': entries,
                'permissions': get_file_permissions(file_path),
                'folder_permissions': folder_perms,
                'can_delete': dir_can_delete
            })
        except PermissionError:
            return jsonify({'error': 'Permission denied'}), 403

    # 文件
    size = os.path.getsize(file_path)
    if size > MAX_FILE_PREVIEW_SIZE:
        limit_mb = MAX_FILE_PREVIEW_SIZE // (1024 * 1024)
        return jsonify({'error': f'File too large ({size} bytes). Limit is {limit_mb} MB.'}), 413

    try:
        with open(file_path, 'rb') as f:
            raw = f.read()
        try:
            content = raw.decode('utf-8')
            encoding = 'utf-8'
        except UnicodeDecodeError:
            try:
                content = raw.decode('gbk')
                encoding = 'gbk'
            except UnicodeDecodeError:
                return jsonify({'error': 'Binary file, cannot display as text'}), 415

        return jsonify({
            'type': 'file',
            'path': file_path,
            'size': size,
            'encoding': encoding,
            'content': content,
            'permissions': get_file_permissions(file_path),
            'folder_permissions': folder_perms
        })
    except PermissionError:
        return jsonify({'error': 'Permission denied'}), 403


@app.route('/api/file/save', methods=['POST'])
def file_save():
    if not require_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        data = request.json
        file_path = data.get('path', '')
        content = data.get('content', '')

        if not file_path:
            return jsonify({'error': "Missing 'path' parameter"}), 400

        file_path = os.path.normpath(file_path)
        allowed, reason = check_permission(file_path, 'write')
        if not allowed:
            return jsonify({'error': reason}), 403

        if os.path.exists(file_path):
            shutil.copy2(file_path, file_path + '.bak')

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)

        return jsonify({'success': True, 'path': file_path, 'size': len(content.encode('utf-8'))})
    except PermissionError:
        return jsonify({'error': 'Permission denied'}), 403
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/file/create', methods=['POST'])
def file_create():
    if not require_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        data = request.json
        # Support both 'path' and 'parent+name' format
        path = data.get('path', '')
        if not path:
            parent = data.get('parent', '')
            name = data.get('name', '')
            if not parent or not name:
                return jsonify({'error': "Missing 'path' or 'parent'+'name' parameters"}), 400
            path = os.path.join(parent, name)
        file_type = data.get('type', 'file')

        path = os.path.normpath(path)
        parent = os.path.dirname(path)

        if not os.path.exists(parent):
            return jsonify({'error': 'Parent directory does not exist'}), 400

        allowed, reason = check_permission(parent, 'write')
        if not allowed:
            return jsonify({'error': reason}), 403

        if os.path.exists(path):
            return jsonify({'error': 'File or directory already exists'}), 400

        if file_type == 'directory':
            os.makedirs(path)
        else:
            with open(path, 'w') as f:
                pass

        return jsonify({'success': True, 'path': path})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/file/delete', methods=['POST'])
def file_delete():
    if not require_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        data = request.json
        paths = data.get('paths', [])

        if not paths:
            return jsonify({'error': "Missing 'paths' parameter"}), 400

        deleted = []
        failed = []

        for path in paths:
            path = os.path.normpath(path)
            if not os.path.exists(path):
                failed.append({'path': path, 'error': 'File not found'})
                continue
            if not is_in_whitelist(path):
                failed.append({'path': path, 'error': 'Not in whitelist'})
                continue

            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                deleted.append(path)
            except Exception as e:
                failed.append({'path': path, 'error': str(e)})

        msg = f'已删除 {len(deleted)} 项'
        if failed:
            msg += f'，{len(failed)} 项失败'

        return jsonify({'success': True, 'deleted': deleted, 'failed': failed, 'message': msg})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/file/chmod', methods=['POST'])
def file_chmod():
    if not require_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        data = request.json
        path = data.get('path', '')
        mode = data.get('mode', '755')

        if not path:
            return jsonify({'error': "Missing 'path' parameter"}), 400

        path = os.path.normpath(path)
        if not os.path.exists(path):
            return jsonify({'error': 'File not found'}), 404

        allowed, reason = check_permission(path, 'write')
        if not allowed:
            return jsonify({'error': reason}), 403

        mode_int = int(mode, 8)
        os.chmod(path, mode_int)

        return jsonify({'success': True, 'path': path, 'mode': mode})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/file/upload', methods=['POST'])
def file_upload():
    if not require_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        path = request.form.get('path')
        if not path:
            return jsonify({'error': 'Missing path'}), 400

        file = request.files.get('file')
        if not file:
            return jsonify({'error': 'No file uploaded'}), 400

        path = os.path.normpath(path)
        parent = os.path.dirname(path)

        allowed, reason = check_permission(parent, 'write')
        if not allowed:
            return jsonify({'error': reason}), 403

        # 处理文件名冲突
        final_path = path
        counter = 1
        while os.path.exists(final_path):
            base, ext = os.path.splitext(path)
            final_path = f'{base}_{counter}{ext}'
            counter += 1

        file.save(final_path)

        return jsonify({'success': True, 'path': final_path})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/file/download', methods=['GET'])
def file_download():
    if not require_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    path = request.args.get('path', '')
    if not path:
        return jsonify({'error': "Missing 'path' parameter"}), 400

    path = os.path.normpath(path)
    if not os.path.exists(path):
        return jsonify({'error': 'File not found'}), 404

    allowed, reason = check_permission(path, 'read')
    if not allowed:
        return jsonify({'error': reason}), 403

    if os.path.isdir(path):
        import urllib.parse
        dirname = os.path.basename(path) or 'root'

        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
            tmp_path = tmp.name

        with zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(path):
                for file in files:
                    file_full = os.path.join(root, file)
                    arcname = os.path.relpath(file_full, os.path.dirname(path))
                    zf.write(file_full, arcname)

        return send_file(tmp_path, as_attachment=True, download_name=f"{dirname}.zip")

    else:
        import urllib.parse
        filename = os.path.basename(path)
        return send_from_directory(os.path.dirname(path), filename, as_attachment=True)


@app.route('/api/file/download/batch', methods=['POST'])
def batch_download():
    if not require_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        data = request.json
        paths = data.get('paths', [])

        if not paths:
            return jsonify({'error': "Missing 'paths' parameter"}), 400

        for p in paths:
            allowed, reason = check_permission(p, 'read')
            if not allowed:
                return jsonify({'error': f'Access denied: {p}'}), 403

        import tempfile
        import urllib.parse

        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
            tmp_path = tmp.name

        with zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for path in paths:
                path = os.path.normpath(path)
                if os.path.isdir(path):
                    for root, dirs, files in os.walk(path):
                        for file in files:
                            file_full = os.path.join(root, file)
                            arcname = os.path.relpath(file_full, os.path.dirname(path))
                            zf.write(file_full, arcname)
                else:
                    zf.write(path, os.path.basename(path))

        return send_file(tmp_path, as_attachment=True, download_name="download.zip")
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/whitelist', methods=['GET', 'POST', 'DELETE', 'PUT'])
def whitelist():
    if not require_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    if request.method == 'GET':
        whitelist = load_whitelist()
        return jsonify({'whitelist': format_whitelist_with_types(whitelist)})

    try:
        data = request.json
        action = data.get('action', '')

        if action == 'add':
            path = data.get('path', '')
            if not path:
                return jsonify({'error': "Missing 'path' parameter"}), 400

            normalized = os.path.normpath(path)
            if not os.path.exists(normalized):
                return jsonify({'error': f'路径不存在: {normalized}'}), 400

            whitelist = load_whitelist()
            if normalized not in [os.path.normpath(p) for p in whitelist]:
                whitelist.append(normalized)
                if save_whitelist(whitelist):
                    path_type = '文件' if os.path.isfile(normalized) else '目录'
                    return jsonify({'success': True, 'whitelist': format_whitelist_with_types(whitelist), 'type': path_type})
                else:
                    return jsonify({'error': '保存白名单失败'}), 500
            else:
                return jsonify({'success': True, 'whitelist': format_whitelist_with_types(whitelist), 'message': '路径已存在于白名单中'})

        elif action == 'remove':
            path = data.get('path', '')
            if not path:
                return jsonify({'error': "Missing 'path' parameter"}), 400

            whitelist = load_whitelist()
            normalized = os.path.normpath(path)
            new_whitelist = [p for p in whitelist if os.path.normpath(p) != normalized]

            if len(new_whitelist) < len(whitelist):
                if save_whitelist(new_whitelist):
                    return jsonify({'success': True, 'whitelist': format_whitelist_with_types(new_whitelist)})
                else:
                    return jsonify({'error': '保存白名单失败'}), 500
            else:
                return jsonify({'error': '路径不在白名单中', 'whitelist': format_whitelist_with_types(whitelist)}), 400

        elif action == 'set':
            whitelist = data.get('whitelist', [])
            if not isinstance(whitelist, list):
                return jsonify({'error': 'Invalid whitelist format'}), 400

            normalized_whitelist = [os.path.normpath(p) for p in whitelist if p]
            if save_whitelist(normalized_whitelist):
                return jsonify({'success': True, 'whitelist': format_whitelist_with_types(normalized_whitelist)})
            else:
                return jsonify({'error': '保存白名单失败'}), 500

        else:
            whitelist = load_whitelist()
            return jsonify({'whitelist': format_whitelist_with_types(whitelist)})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/quickpaths', methods=['GET'])
def quickpaths_get():
    if not require_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify({'quick_paths': get_quick_paths()})


@app.route('/api/quickpaths', methods=['POST'])
def quickpaths_save():
    if not require_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        data = request.json
        paths = data.get('quick_paths', [])
        if not isinstance(paths, list):
            return jsonify({'error': 'Invalid format'}), 400

        if save_quick_paths(paths):
            return jsonify({'success': True, 'quick_paths': paths})
        else:
            return jsonify({'error': '保存失败'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/changepwd', methods=['POST'])
def changepwd():
    if not require_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        data = request.json
        old_password = data.get('old_password', '')
        new_password = data.get('new_password', '')

        success, message = change_password(old_password, new_password)
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'error': message}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# === 用户配置 API ===
@app.route('/api/userconfig', methods=['GET'])
def userconfig_get():
    """获取用户配置"""
    if not require_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    user_cfg = get_user_config()
    effective = get_effective_config()
    
    return jsonify({
        'config': {
            'session_timeout': user_cfg.get('session_timeout', effective['session_timeout']),
            'default_permissions': user_cfg.get('default_permissions', effective['default_permissions']),
            'download_limits': user_cfg.get('download_limits', effective['download_limits'])
        },
        'defaults': {
            'session_timeout': 3600,
            'default_permissions': {'read': True, 'write': True},
            'download_limits': {
                'max_single_file_size': 100 * 1024 * 1024,
                'max_total_download_size': 200 * 1024 * 1024,
                'max_files_in_zip': 500,
                'max_dir_depth': 20,
                'max_file_preview_size': 2 * 1024 * 1024
            }
        }
    })


@app.route('/api/userconfig', methods=['POST'])
def userconfig_save():
    """保存用户配置"""
    global SESSION_TIMEOUT, DEFAULT_PERMISSIONS
    global MAX_SINGLE_FILE_SIZE, MAX_TOTAL_DOWNLOAD_SIZE, MAX_FILES_IN_ZIP, MAX_DIR_DEPTH, MAX_FILE_PREVIEW_SIZE
    
    if not require_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        data = request.json
        new_config = data.get('config', {})
        
        # 验证配置值
        session_timeout = new_config.get('session_timeout')
        if session_timeout is not None:
            if not isinstance(session_timeout, int) or session_timeout < 60 or session_timeout > 86400:
                return jsonify({'error': '会话超时时间必须在 60-86400 秒之间'}), 400
        
        default_permissions = new_config.get('default_permissions')
        if default_permissions is not None:
            if not isinstance(default_permissions, dict):
                return jsonify({'error': '默认权限格式无效'}), 400
        
        download_limits = new_config.get('download_limits')
        if download_limits is not None:
            if not isinstance(download_limits, dict):
                return jsonify({'error': '下载限制格式无效'}), 400
            for key in ['max_single_file_size', 'max_total_download_size', 'max_file_preview_size']:
                val = download_limits.get(key)
                if val is not None and (not isinstance(val, int) or val < 0):
                    return jsonify({'error': f'{key} 必须为正整数'}), 400
            for key in ['max_files_in_zip', 'max_dir_depth']:
                val = download_limits.get(key)
                if val is not None and (not isinstance(val, int) or val < 1):
                    return jsonify({'error': f'{key} 必须为正整数'}), 400
        
        # 构建新的用户配置
        user_cfg = get_user_config().copy()
        if session_timeout is not None:
            user_cfg['session_timeout'] = session_timeout
        if default_permissions is not None:
            user_cfg['default_permissions'] = default_permissions
        if download_limits is not None:
            user_cfg['download_limits'] = download_limits
        
        if save_user_config(user_cfg):
            # 更新运行时配置
            effective = get_effective_config()
            SESSION_TIMEOUT = effective['session_timeout']
            DEFAULT_PERMISSIONS = effective['default_permissions']
            MAX_SINGLE_FILE_SIZE = effective['download_limits']['max_single_file_size']
            MAX_TOTAL_DOWNLOAD_SIZE = effective['download_limits']['max_total_download_size']
            MAX_FILES_IN_ZIP = effective['download_limits']['max_files_in_zip']
            MAX_DIR_DEPTH = effective['download_limits']['max_dir_depth']
            MAX_FILE_PREVIEW_SIZE = effective['download_limits']['max_file_preview_size']
            
            return jsonify({'success': True, 'config': user_cfg})
        else:
            return jsonify({'error': '保存配置失败'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/userconfig/reset', methods=['POST'])
def userconfig_reset():
    """重置用户配置为默认值"""
    global SESSION_TIMEOUT, DEFAULT_PERMISSIONS
    global MAX_SINGLE_FILE_SIZE, MAX_TOTAL_DOWNLOAD_SIZE, MAX_FILES_IN_ZIP, MAX_DIR_DEPTH, MAX_FILE_PREVIEW_SIZE
    
    if not require_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        if save_user_config({}):
            # 更新运行时配置为默认值
            SESSION_TIMEOUT = 3600
            DEFAULT_PERMISSIONS = {"read": True, "write": True}
            MAX_SINGLE_FILE_SIZE = 100 * 1024 * 1024
            MAX_TOTAL_DOWNLOAD_SIZE = 200 * 1024 * 1024
            MAX_FILES_IN_ZIP = 500
            MAX_DIR_DEPTH = 20
            MAX_FILE_PREVIEW_SIZE = 2 * 1024 * 1024
            
            return jsonify({'success': True, 'message': '配置已重置为默认值'})
        else:
            return jsonify({'error': '重置配置失败'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/userconfig/raw', methods=['GET'])
def userconfig_raw_get():
    """获取原始配置文件内容"""
    if not require_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        if USER_CONFIG_FILE.exists():
            with USER_CONFIG_FILE.open("r", encoding="utf-8") as f:
                content = f.read()
        else:
            content = ""
        return jsonify({'content': content})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/userconfig/raw', methods=['POST'])
def userconfig_raw_save():
    """保存原始配置文件内容"""
    global SESSION_TIMEOUT, DEFAULT_PERMISSIONS
    global MAX_SINGLE_FILE_SIZE, MAX_TOTAL_DOWNLOAD_SIZE, MAX_FILES_IN_ZIP, MAX_DIR_DEPTH, MAX_FILE_PREVIEW_SIZE
    
    if not require_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        data = request.json
        content = data.get('content', '')
        
        # 验证 YAML 格式
        try:
            parsed = yaml.safe_load(content) if content.strip() else {}
            if parsed is None:
                parsed = {}
            if not isinstance(parsed, dict):
                return jsonify({'error': '配置必须是 YAML 对象格式'}), 400
        except yaml.YAMLError as e:
            return jsonify({'error': f'YAML 格式错误: {str(e)}'}), 400
        
        # 保存配置文件
        USER_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with USER_CONFIG_FILE.open("w", encoding="utf-8") as f:
            f.write(content)
        
        # 更新运行时配置
        global _user_config
        _user_config = parsed
        
        effective = get_effective_config()
        SESSION_TIMEOUT = effective['session_timeout']
        DEFAULT_PERMISSIONS = effective['default_permissions']
        MAX_SINGLE_FILE_SIZE = effective['download_limits']['max_single_file_size']
        MAX_TOTAL_DOWNLOAD_SIZE = effective['download_limits']['max_total_download_size']
        MAX_FILES_IN_ZIP = effective['download_limits']['max_files_in_zip']
        MAX_DIR_DEPTH = effective['download_limits']['max_dir_depth']
        MAX_FILE_PREVIEW_SIZE = effective['download_limits']['max_file_preview_size']
        
        return jsonify({'success': True, 'message': '配置文件已保存'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# === AI / OCR API ===
AI_CONFIG_FILE = DATA_DIR / "ai_config.json"

def load_ai_config() -> dict:
    """加载 AI 配置"""
    try:
        if AI_CONFIG_FILE.exists():
            with AI_CONFIG_FILE.open("r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"Failed to load AI config: {e}")
    return {}

def save_ai_config(config: dict) -> bool:
    """保存 AI 配置"""
    try:
        AI_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with AI_CONFIG_FILE.open("w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Failed to save AI config: {e}")
        return False


@app.route('/api/ai/config', methods=['GET'])
def get_ai_config():
    """获取 AI 配置（不返回完整 API Key）"""
    if not require_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    config = load_ai_config()
    api_key = config.get("api_key", "")
    if api_key:
        masked_key = api_key[:8] + "*" * (len(api_key) - 12) + api_key[-4:] if len(api_key) > 12 else "****"
    else:
        masked_key = ""
    
    return jsonify({
        "api_key": masked_key,
        "has_key": bool(api_key),
        "model": config.get("model", "deepseek-ai/DeepSeek-OCR"),
        "base_url": config.get("base_url", "https://api.siliconflow.cn/v1")
    })


@app.route('/api/ai/models', methods=['GET'])
def get_ai_models():
    """获取可用模型列表"""
    if not require_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    models = [
        {"id": "deepseek-ai/DeepSeek-OCR", "name": "DeepSeek OCR"},
        {"id": "Qwen/Qwen2-VL-7B-Instruct", "name": "Qwen2-VL-7B"},
        {"id": "Qwen/Qwen2-VL-72B-Instruct", "name": "Qwen2-VL-72B"},
        {"id": "OpenGVLab/InternVL2-26B", "name": "InternVL2-26B"},
        {"id": "OpenGVLab/InternVL2-8B", "name": "InternVL2-8B"},
        {"id": "Pro/Qwen/Qwen2-VL-7B-Instruct", "name": "Qwen2-VL-7B Pro"},
    ]
    return jsonify(models)


@app.route('/api/ai/ocr', methods=['POST'])
def ai_ocr():
    """OCR 接口 - 调用 SiliconFlow DeepSeek-OCR"""
    if not require_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    config = load_ai_config()
    data = request.json
    image_base64 = data.get("image", "")
    prompt_type = data.get("prompt_type", "ocr")

    # 从配置获取默认值
    default_api_key = os.environ.get("OCR_API_KEY", "")
    default_ocr_model = "deepseek-ai/DeepSeek-OCR"
    
    # 优先级：前端传入 > 已保存配置 > 默认配置
    input_api_key = data.get("api_key", "")
    api_key = input_api_key or config.get("api_key", "") or default_api_key
    model = data.get("model", "") or config.get("model", "") or default_ocr_model

    if not image_base64:
        return jsonify({'error': '请上传图片'}), 400

    # 如果前端传入了新的 API Key，保存它
    if input_api_key and not input_api_key.startswith("sk-****"):
        config["api_key"] = input_api_key
        if model:
            config["model"] = model
        save_ai_config(config)

    # 根据类型选择不同的提示词
    prompts = {
        "ocr": "<image>\n<|grounding|>OCR this image.",
        "markdown": "<image>\n<|grounding|>Convert the document to markdown.",
        "free": "<image>\nFree OCR."
    }
    prompt = prompts.get(prompt_type, prompts["ocr"])

    try:
        import urllib.request
        import urllib.error

        base_url = config.get("base_url", "https://api.siliconflow.cn/v1")
        url = f"{base_url.rstrip('/')}/chat/completions"

        request_data = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}"
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ],
            "max_tokens": 4096
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(request_data).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            },
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))

            if "choices" in result and len(result["choices"]) > 0:
                content = result["choices"][0].get("message", {}).get("content", "")
                
                # 从 <|ref|>文字<|/ref|><|det|>坐标<|/det|> 格式中提取文字
                # 先提取所有 <|ref|>...<|/ref|> 中的文字
                texts = re.findall(r'<\|ref\|>(.*?)<\|\/ref\|>', content, flags=re.DOTALL)
                output = '\n'.join(texts)
                output = re.sub(r'\n{3,}', '\n\n', output)
                output = output.strip()

                return jsonify({
                    "success": True,
                    "output": output,
                    "raw": content,
                    "model": result.get("model", model)
                })
            else:
                return jsonify({'error': '无响应内容'}), 500

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        try:
            error_json = json.loads(error_body)
            error_msg = error_json.get("error", {}).get("message", error_body)
        except:
            error_msg = error_body or str(e)
        return jsonify({'error': f'API 错误: {error_msg}'}), 500
    except urllib.error.URLError as e:
        return jsonify({'error': f'网络错误: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'请求失败: {str(e)}'}), 500


# === 启动服务器 ===
if __name__ == '__main__':
    print(f"Starting File Viewer Server on http://{SERVER_HOST}:{SERVER_PORT}")
    socketio.run(app, host=SERVER_HOST, port=SERVER_PORT, debug=False, allow_unsafe_werkzeug=True)