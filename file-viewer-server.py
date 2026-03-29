#!/usr/bin/env python3
"""
File Viewer Backend Service with Authentication
"""

import http.server
import json
import os
import stat
import urllib.parse
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

# === 配置文件路径 ===
CONFIG_FILE = Path("/etc/file-viewer/config.yaml")
PROJECT_CONFIG_FILE = Path(__file__).parent / "config.yaml"

# 全局配置对象
_config = None
_config_file_path = None


def load_config() -> dict:
    """加载 YAML 配置文件"""
    global _config, _config_file_path
    # 优先使用系统配置，其次使用项目目录配置
    config_path = CONFIG_FILE if CONFIG_FILE.exists() else PROJECT_CONFIG_FILE
    
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
        config_path = _config_file_path or CONFIG_FILE
        # 确保目录存在
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


# 加载配置
load_config()

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
SESSION_TIMEOUT = _server_cfg.get("session_timeout", 3600)
SECRET_KEY = secrets.token_bytes(32)

# 数据存储路径
PASSWORD_FILE = Path(_storage_cfg.get("password_file", "/etc/file-viewer/passwd"))

# 文件夹权限配置
FOLDER_PERMISSIONS = _permissions_cfg.get("folder_permissions", {})
DEFAULT_PERMISSIONS = _permissions_cfg.get("default_permissions", {"read": True, "write": True})

# 下载限制配置
MAX_SINGLE_FILE_SIZE = _download_cfg.get("max_single_file_size", 100 * 1024 * 1024)
MAX_TOTAL_DOWNLOAD_SIZE = _download_cfg.get("max_total_download_size", 200 * 1024 * 1024)
MAX_FILES_IN_ZIP = _download_cfg.get("max_files_in_zip", 500)
MAX_DIR_DEPTH = _download_cfg.get("max_dir_depth", 20)
MAX_FILE_PREVIEW_SIZE = _download_cfg.get("max_file_preview_size", 2 * 1024 * 1024)


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
    """获取快捷路径配置（从主配置文件）"""
    return _ui_cfg.get("quick_paths", [])


def save_quick_paths(paths: list) -> bool:
    """保存快捷路径配置（到主配置文件）"""
    global _config, _ui_cfg
    if "ui" not in _config:
        _config["ui"] = {}
    _config["ui"]["quick_paths"] = paths
    _ui_cfg["quick_paths"] = paths
    return save_config()


def get_quick_cmds() -> list:
    """获取快捷命令配置（从主配置文件）"""
    return _ui_cfg.get("quick_commands", [])


def save_quick_cmds(cmds: list) -> bool:
    """保存快捷命令配置（到主配置文件）"""
    global _config, _ui_cfg
    if "ui" not in _config:
        _config["ui"] = {}
    _config["ui"]["quick_commands"] = cmds
    _ui_cfg["quick_commands"] = cmds
    return save_config()


def is_in_whitelist(path: str) -> bool:
    """检查路径是否在白名单中"""
    whitelist = load_whitelist()
    normalized_path = os.path.normpath(path)
    for allowed_path in whitelist:
        normalized_allowed = os.path.normpath(allowed_path)
        # 检查路径是否以白名单路径开头
        if normalized_path == normalized_allowed or normalized_path.startswith(normalized_allowed + os.sep):
            return True
    return False


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
        # delete 操作由白名单控制，默认允许
        if action == "delete":
            return True, "allowed"
        if action == "read":
            return True, "allowed"
        else:
            return False, f"{action} permission denied by default"


def verify_password(password: str) -> bool:
    if not PASSWORD_FILE.exists():
        return False
    try:
        with PASSWORD_FILE.open("r") as f:
            stored_hash = f.read().strip()
        return hmac.compare_digest(
            stored_hash,
            hashlib.sha256(password.encode()).hexdigest()
        )
    except Exception:
        return False


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


class FileViewerHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_json(self, status, data, headers=None):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def get_cookie(self, name: str):
        for cookie in self.headers.get("Cookie", "").split(";"):
            if "=" in cookie:
                k, v = cookie.strip().split("=", 1)
                if k == name:
                    return v
        return None

    def require_auth(self) -> bool:
        sid = self.get_cookie("sessionid")
        if not sid or not get_session(sid):
            self.send_json(401, {"error": "Unauthorized"})
            return False
        return True

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Cookie")
        self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/login":
            try:
                length = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(length).decode("utf-8"))
                if verify_password(data.get("password", "")):
                    sid = create_session("admin")
                    self.send_json(200, {"success": True}, {"Set-Cookie": f"sessionid={sid}; Path=/; Max-Age={SESSION_TIMEOUT}; HttpOnly; SameSite=Strict"})
                else:
                    self.send_json(401, {"error": "Invalid password"})
            except Exception:
                self.send_json(400, {"error": "Bad request"})
        elif parsed.path == "/api/logout":
            if self.require_auth():
                sid = self.get_cookie("sessionid")
                if sid:
                    delete_session(sid)
                self.send_json(200, {"success": True}, {"Set-Cookie": "sessionid=; Path=/; Max-Age=0"})
        elif parsed.path == "/api/file/save":
            if self.require_auth():
                self._handle_save_file()
        elif parsed.path == "/api/file/create":
            if self.require_auth():
                self._handle_create()
        elif parsed.path == "/api/file/chmod":
            if self.require_auth():
                self._handle_chmod()
        elif parsed.path == "/api/file/upload":
            if self.require_auth():
                self._handle_upload()
        elif parsed.path == "/api/file/delete":
            if self.require_auth():
                self._handle_delete()
        elif parsed.path == "/api/file/download/batch":
            if self.require_auth():
                self._handle_batch_download()
        elif parsed.path == "/api/whitelist":
            if self.require_auth():
                self._handle_whitelist()
        elif parsed.path == "/api/quickpaths":
            if self.require_auth():
                self._handle_quickpaths()
        elif parsed.path == "/api/quickcmds":
            if self.require_auth():
                self._handle_quickcmds()
        elif parsed.path == "/api/terminal":
            if self.require_auth():
                self._handle_terminal()
        elif parsed.path == "/api/terminal/complete":
            if self.require_auth():
                self._handle_terminal_complete()
        else:
            self.send_json(404, {"error": "Not Found"})

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            # 提供静态文件 index.html
            self._serve_static_file("index.html")
        elif parsed.path == "/api/auth/check":
            sid = self.get_cookie("sessionid")
            self.send_json(200, {"authenticated": bool(get_session(sid))})
        elif parsed.path == "/api/system":
            if self.require_auth():
                self.send_json(200, collect_system_info())
        elif parsed.path == "/api/file":
            if self.require_auth():
                self._handle_file(parsed)
        elif parsed.path == "/api/file/download":
            if self.require_auth():
                self._handle_single_download(parsed)
        else:
            self.send_json(404, {"error": "Not Found"})
    
    def _serve_static_file(self, filename):
        """提供静态文件服务"""
        try:
            # 使用项目目录下的静态文件
            project_dir = Path("/home/file-viewer")
            file_path = project_dir / filename
            
            if not file_path.exists():
                self.send_json(404, {"error": "File not found"})
                return
            
            # 确定 MIME 类型
            mime_types = {
                ".html": "text/html; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".json": "application/json; charset=utf-8",
            }
            ext = file_path.suffix.lower()
            mime_type = mime_types.get(ext, "application/octet-stream")
            
            with open(file_path, "rb") as f:
                content = f.read()
            
            self.send_response(200)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_json(500, {"error": str(e)})

    def _handle_file(self, parsed):
        params = urllib.parse.parse_qs(parsed.query)
        path_list = params.get("path", [])
        if not path_list:
            self.send_json(400, {"error": "Missing 'path' parameter"})
            return
        file_path = os.path.normpath(path_list[0])
        if not os.path.exists(file_path):
            self.send_json(404, {"error": f"File not found: {file_path}"})
            return
        allowed, reason = check_permission(file_path, "read")
        if not allowed:
            self.send_json(403, {"error": reason})
            return
        folder_perms = get_folder_permission_config(file_path)
        if os.path.isdir(file_path):
            try:
                entries = []
                for name in sorted(os.listdir(file_path)):
                    full = os.path.join(file_path, name)
                    entries.append({
                        "name": name,
                        "type": "dir" if os.path.isdir(full) else "file",
                        "size": os.path.getsize(full) if os.path.isfile(full) else None,
                        "permissions": get_file_permissions(full),
                        "can_delete": is_in_whitelist(full),
                    })
                # 检查当前目录是否在白名单中（用于批量删除按钮）
                dir_can_delete = is_in_whitelist(file_path)
                self.send_json(200, {"type": "directory", "path": file_path, "entries": entries, "permissions": get_file_permissions(file_path), "folder_permissions": folder_perms, "can_delete": dir_can_delete})
            except PermissionError:
                self.send_json(403, {"error": "Permission denied"})
            return
        size = os.path.getsize(file_path)
        if size > MAX_FILE_PREVIEW_SIZE:
            limit_mb = MAX_FILE_PREVIEW_SIZE // (1024 * 1024)
            self.send_json(413, {"error": f"File too large ({size} bytes). Limit is {limit_mb} MB."})
            return
        try:
            with open(file_path, "rb") as f:
                raw = f.read()
            try:
                file_content = raw.decode("utf-8")
                encoding = "utf-8"
            except UnicodeDecodeError:
                try:
                    file_content = raw.decode("gbk")
                    encoding = "gbk"
                except UnicodeDecodeError:
                    self.send_json(415, {"error": "Binary file, cannot display as text"})
                    return
            self.send_json(200, {"type": "file", "path": file_path, "size": size, "encoding": encoding, "content": file_content, "permissions": get_file_permissions(file_path), "folder_permissions": folder_perms})
        except PermissionError:
            self.send_json(403, {"error": "Permission denied"})

    def _handle_single_download(self, parsed):
        params = urllib.parse.parse_qs(parsed.query)
        path_list = params.get("path", [])
        if not path_list:
            self.send_json(400, {"error": "Missing 'path' parameter"})
            return
        file_path = os.path.normpath(path_list[0])
        if not os.path.exists(file_path):
            self.send_json(404, {"error": f"File not found: {file_path}"})
            return
        allowed, reason = check_permission(file_path, "read")
        if not allowed:
            self.send_json(403, {"error": reason})
            return
        if os.path.isdir(file_path):
            self._send_directory_as_zip(file_path)
        else:
            self._send_file(file_path)

    def _send_file(self, file_path):
        try:
            size = os.path.getsize(file_path)
            if size > MAX_SINGLE_FILE_SIZE:
                self.send_json(413, {"error": f"文件过大 ({size // (1024*1024)} MB)，超过限制 ({MAX_SINGLE_FILE_SIZE // (1024*1024)} MB)"})
                return
            filename = os.path.basename(file_path)
            with open(file_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.send_header("Content-Disposition", f'attachment; filename="{urllib.parse.quote(filename)}"')
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_json(500, {"error": str(e)})

    def _send_directory_as_zip(self, dir_path):
        try:
            # 检查目录大小和文件数
            total_size, file_count = get_dir_size_and_count(dir_path)
            
            if file_count > MAX_FILES_IN_ZIP:
                self.send_json(413, {"error": f"目录文件过多 ({file_count})，超过限制 ({MAX_FILES_IN_ZIP})"})
                return
            if total_size > MAX_TOTAL_DOWNLOAD_SIZE:
                self.send_json(413, {"error": f"目录过大 ({total_size // (1024*1024)} MB)，超过限制 ({MAX_TOTAL_DOWNLOAD_SIZE // (1024*1024)} MB)"})
                return
            
            dirname = os.path.basename(dir_path) or "root"
            zip_buffer = io.BytesIO()
            
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                current_files = 0
                current_size = 0
                for root, dirs, files in os.walk(dir_path):
                    depth = root[len(dir_path):].count(os.sep)
                    if depth > MAX_DIR_DEPTH:
                        continue
                    for file in files:
                        if current_files >= MAX_FILES_IN_ZIP:
                            break
                        file_full = os.path.join(root, file)
                        try:
                            file_size = os.path.getsize(file_full)
                            if file_size > MAX_SINGLE_FILE_SIZE:
                                continue  # 跳过超大文件
                            if current_size + file_size > MAX_TOTAL_DOWNLOAD_SIZE:
                                continue  # 跳过以保持总大小限制
                            arcname = os.path.relpath(file_full, os.path.dirname(dir_path))
                            zf.write(file_full, arcname)
                            current_files += 1
                            current_size += file_size
                        except OSError:
                            pass
                    for d in dirs:
                        dir_full = os.path.join(root, d)
                        if not os.listdir(dir_full):
                            arcname = os.path.relpath(dir_full, os.path.dirname(dir_path)) + '/'
                            zf.write(dir_full, arcname)
            
            zip_data = zip_buffer.getvalue()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(zip_data)))
            self.send_header("Content-Disposition", f'attachment; filename="{urllib.parse.quote(dirname)}.zip"')
            self.end_headers()
            self.wfile.write(zip_data)
        except Exception as e:
            self.send_json(500, {"error": str(e)})

    def _handle_batch_download(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            paths = data.get("paths", [])
            if not paths:
                self.send_json(400, {"error": "Missing 'paths' parameter"})
                return
            for p in paths:
                allowed, reason = check_permission(p, "read")
                if not allowed:
                    self.send_json(403, {"error": f"Access denied: {p}"})
                    return
            if len(paths) == 1:
                file_path = os.path.normpath(paths[0])
                if os.path.isdir(file_path):
                    self._send_directory_as_zip(file_path)
                else:
                    self._send_file(file_path)
                return
            
            # 批量下载 - 预检查大小
            total_size = 0
            file_count = 0
            for p in paths:
                p = os.path.normpath(p)
                if os.path.isdir(p):
                    s, c = get_dir_size_and_count(p)
                    total_size += s
                    file_count += c
                elif os.path.isfile(p):
                    total_size += os.path.getsize(p)
                    file_count += 1
                if file_count > MAX_FILES_IN_ZIP:
                    self.send_json(413, {"error": f"文件数量过多 ({file_count})，超过限制 ({MAX_FILES_IN_ZIP})"})
                    return
                if total_size > MAX_TOTAL_DOWNLOAD_SIZE:
                    self.send_json(413, {"error": f"总大小过大 ({total_size // (1024*1024)} MB)，超过限制 ({MAX_TOTAL_DOWNLOAD_SIZE // (1024*1024)} MB)"})
                    return
            
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                for file_path in paths:
                    file_path = os.path.normpath(file_path)
                    if not os.path.exists(file_path):
                        continue
                    if os.path.isdir(file_path):
                        dirname = os.path.basename(file_path)
                        for root, dirs, files in os.walk(file_path):
                            for file in files:
                                file_full = os.path.join(root, file)
                                try:
                                    if os.path.getsize(file_full) > MAX_SINGLE_FILE_SIZE:
                                        continue
                                    arcname = os.path.join(dirname, os.path.relpath(file_full, file_path))
                                    zf.write(file_full, arcname)
                                except OSError:
                                    pass
                    else:
                        try:
                            if os.path.getsize(file_path) > MAX_SINGLE_FILE_SIZE:
                                continue
                            zf.write(file_path, os.path.basename(file_path))
                        except OSError:
                            pass
            
            zip_data = zip_buffer.getvalue()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(zip_data)))
            self.send_header("Content-Disposition", 'attachment; filename="download.zip"')
            self.end_headers()
            self.wfile.write(zip_data)
        except Exception as e:
            self.send_json(500, {"error": str(e)})

    def _handle_delete(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            paths = data.get("paths", [])
            if not paths:
                self.send_json(400, {"error": "Missing 'paths' parameter"})
                return
            deleted, failed = [], []
            whitelist = load_whitelist()
            for file_path in paths:
                file_path = os.path.normpath(file_path)
                # 检查白名单
                if not is_in_whitelist(file_path):
                    failed.append({"path": file_path, "error": "路径不在删除白名单中"})
                    continue
                allowed, reason = check_permission(file_path, "delete")
                if not allowed:
                    failed.append({"path": file_path, "error": reason})
                    continue
                if not os.path.exists(file_path):
                    failed.append({"path": file_path, "error": "File not found"})
                    continue
                try:
                    if os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                    else:
                        os.remove(file_path)
                    deleted.append(file_path)
                except Exception as e:
                    failed.append({"path": file_path, "error": str(e)})
            self.send_json(200, {"success": True, "deleted": deleted, "failed": failed, "message": f"已删除 {len(deleted)} 项" + (f"，{len(failed)} 项失败" if failed else "")})
        except Exception as e:
            self.send_json(500, {"error": str(e)})

    def _handle_whitelist(self):
        """处理白名单管理请求"""
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length == 0:
                # GET 请求 - 获取白名单
                whitelist = load_whitelist()
                self.send_json(200, {"whitelist": whitelist})
                return
            
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            action = data.get("action", "")
            
            if action == "add":
                path = data.get("path", "")
                if not path:
                    self.send_json(400, {"error": "Missing 'path' parameter"})
                    return
                whitelist = load_whitelist()
                normalized = os.path.normpath(path)
                if normalized not in [os.path.normpath(p) for p in whitelist]:
                    whitelist.append(normalized)
                    if save_whitelist(whitelist):
                        self.send_json(200, {"success": True, "whitelist": whitelist})
                    else:
                        self.send_json(500, {"error": "保存白名单失败"})
                else:
                    self.send_json(200, {"success": True, "whitelist": whitelist, "message": "路径已存在于白名单中"})
            
            elif action == "remove":
                path = data.get("path", "")
                if not path:
                    self.send_json(400, {"error": "Missing 'path' parameter"})
                    return
                whitelist = load_whitelist()
                normalized = os.path.normpath(path)
                new_whitelist = [p for p in whitelist if os.path.normpath(p) != normalized]
                if len(new_whitelist) < len(whitelist):
                    if save_whitelist(new_whitelist):
                        self.send_json(200, {"success": True, "whitelist": new_whitelist})
                    else:
                        self.send_json(500, {"error": "保存白名单失败"})
                else:
                    self.send_json(200, {"success": True, "whitelist": whitelist, "message": "路径不在白名单中"})
            
            elif action == "set":
                whitelist = data.get("whitelist", [])
                if not isinstance(whitelist, list):
                    self.send_json(400, {"error": "Invalid whitelist format"})
                    return
                # 规范化所有路径
                normalized_whitelist = [os.path.normpath(p) for p in whitelist if p]
                if save_whitelist(normalized_whitelist):
                    self.send_json(200, {"success": True, "whitelist": normalized_whitelist})
                else:
                    self.send_json(500, {"error": "保存白名单失败"})
            
            else:
                # 默认返回当前白名单
                whitelist = load_whitelist()
                self.send_json(200, {"whitelist": whitelist})
        
        except Exception as e:
            self.send_json(500, {"error": str(e)})

    def _handle_quickpaths(self):
        """处理快捷路径配置请求"""
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length == 0:
                # 获取快捷路径
                paths = get_quick_paths()
                self.send_json(200, {"quick_paths": paths})
                return
            
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            action = data.get("action", "")
            
            if action == "set":
                paths = data.get("quick_paths", [])
                if not isinstance(paths, list):
                    self.send_json(400, {"error": "Invalid format"})
                    return
                if save_quick_paths(paths):
                    self.send_json(200, {"success": True, "quick_paths": paths})
                else:
                    self.send_json(500, {"error": "保存失败"})
            else:
                paths = get_quick_paths()
                self.send_json(200, {"quick_paths": paths})
                
        except Exception as e:
            self.send_json(500, {"error": str(e)})

    def _handle_quickcmds(self):
        """处理快捷命令配置请求"""
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length == 0:
                # 获取快捷命令
                cmds = get_quick_cmds()
                self.send_json(200, {"quick_cmds": cmds})
                return
            
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            action = data.get("action", "")
            
            if action == "set":
                cmds = data.get("quick_cmds", [])
                if not isinstance(cmds, list):
                    self.send_json(400, {"error": "Invalid format"})
                    return
                if save_quick_cmds(cmds):
                    self.send_json(200, {"success": True, "quick_cmds": cmds})
                else:
                    self.send_json(500, {"error": "保存失败"})
            else:
                cmds = get_quick_cmds()
                self.send_json(200, {"quick_cmds": cmds})
                
        except Exception as e:
            self.send_json(500, {"error": str(e)})

    def _handle_save_file(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            file_path = data.get("path", "")
            file_content = data.get("content", "")
            if not file_path:
                self.send_json(400, {"error": "Missing 'path' parameter"})
                return
            file_path = os.path.normpath(file_path)
            allowed, reason = check_permission(file_path, "write")
            if not allowed:
                self.send_json(403, {"error": reason})
                return
            if os.path.exists(file_path):
                shutil.copy2(file_path, file_path + ".bak")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(file_content)
            self.send_json(200, {"success": True, "path": file_path, "size": len(file_content.encode("utf-8"))})
        except PermissionError:
            self.send_json(403, {"error": "Permission denied"})
        except Exception as e:
            self.send_json(500, {"error": str(e)})

    def _handle_create(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            parent_path = data.get("parent", "")
            name = os.path.basename(data.get("name", ""))
            item_type = data.get("type", "file")
            if not parent_path or not name:
                self.send_json(400, {"error": "Missing 'parent' or 'name' parameter"})
                return
            full_path = os.path.normpath(os.path.join(parent_path, name))
            allowed, reason = check_permission(full_path, "write")
            if not allowed:
                self.send_json(403, {"error": reason})
                return
            if os.path.exists(full_path):
                self.send_json(409, {"error": "Already exists"})
                return
            if item_type == "directory":
                os.makedirs(full_path, exist_ok=False)
            else:
                open(full_path, "w").close()
            self.send_json(200, {"success": True, "path": full_path})
        except PermissionError:
            self.send_json(403, {"error": "Permission denied"})
        except Exception as e:
            self.send_json(500, {"error": str(e)})

    def _handle_chmod(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            file_path = data.get("path", "")
            mode = data.get("mode", "")
            if not file_path or not mode:
                self.send_json(400, {"error": "Missing 'path' or 'mode' parameter"})
                return
            file_path = os.path.normpath(file_path)
            allowed, reason = check_permission(file_path, "write")
            if not allowed:
                self.send_json(403, {"error": reason})
                return
            mode_int = int(mode, 8) if isinstance(mode, str) else mode
            os.chmod(file_path, mode_int)
            self.send_json(200, {"success": True, "path": file_path, "mode": oct(mode_int)})
        except PermissionError:
            self.send_json(403, {"error": "Permission denied"})
        except Exception as e:
            self.send_json(500, {"error": str(e)})

    def _handle_upload(self):
        try:
            import cgi
            content_type = self.headers.get("Content-Type", "")
            if "multipart/form-data" not in content_type:
                self.send_json(400, {"error": "Content-Type must be multipart/form-data"})
                return
            form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type})
            dest_dir = os.path.normpath(form.getvalue("path", ""))
            if not dest_dir:
                self.send_json(400, {"error": "Missing 'path' parameter"})
                return
            allowed, reason = check_permission(dest_dir, "write")
            if not allowed:
                self.send_json(403, {"error": reason})
                return
            file_item = form["file"]
            if not file_item.filename:
                self.send_json(400, {"error": "No file uploaded"})
                return
            filename = os.path.basename(file_item.filename)
            dest_path = os.path.join(dest_dir, filename)
            if os.path.exists(dest_path):
                base, ext = os.path.splitext(filename)
                counter = 1
                while os.path.exists(dest_path):
                    filename = f"{base}_{counter}{ext}"
                    dest_path = os.path.join(dest_dir, filename)
                    counter += 1
            with open(dest_path, "wb") as f:
                shutil.copyfileobj(file_item.file, f)
            self.send_json(200, {"success": True, "path": dest_path, "filename": filename, "size": os.path.getsize(dest_path)})
        except PermissionError:
            self.send_json(403, {"error": "Permission denied"})
        except Exception as e:
            self.send_json(500, {"error": str(e)})

    def _handle_terminal(self):
        """处理终端命令执行请求"""
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            command = data.get("command", "")
            cwd = data.get("cwd", "/")
            
            if not command:
                self.send_json(400, {"error": "Missing 'command' parameter"})
                return
            
            # 安全检查：禁止某些危险命令
            dangerous_patterns = [
                r'\brm\s+-rf\s+/(?!\w)',  # rm -rf / 但允许 rm -rf /tmp
                r'\bmkfs\b',
                r'\bdd\s+if=.*of=/dev/',
                r'\b:\(\)\{.*;\};\s*:\(\)',  # fork bomb
                r'\bchmod\s+[-+]?[0-7]*\s+/',
                r'\bchown\s+.*\s+/',
                r'\bshutdown\b',
                r'\breboot\b',
                r'\binit\s+[06]',
                r'\bhalt\b',
                r'\bpoweroff\b',
            ]
            
            for pattern in dangerous_patterns:
                if re.search(pattern, command, re.IGNORECASE):
                    self.send_json(403, {"error": f"命令被禁止执行（安全限制）"})
                    return
            
            # 规范化工作目录
            cwd = os.path.normpath(cwd)
            if not os.path.isdir(cwd):
                cwd = "/"
            
            # 执行命令，并在最后获取pwd
            new_cwd = cwd
            
            try:
                # 如果是cd命令，特殊处理
                cmd_stripped = command.strip()
                if cmd_stripped.startswith('cd ') or cmd_stripped == 'cd':
                    # 解析cd目标
                    parts = cmd_stripped.split(None, 1)
                    target = parts[1] if len(parts) > 1 else ''
                    
                    if not target or target == '~':
                        # cd 或 cd ~ -> 回到家目录
                        new_cwd = os.path.expanduser('~')
                    elif target == '-':
                        # cd - -> 上一个目录（暂不支持，保持当前）
                        new_cwd = cwd
                    else:
                        # 解析相对/绝对路径
                        if target.startswith('/'):
                            new_cwd = target
                        elif target.startswith('~'):
                            new_cwd = os.path.expanduser(target)
                        else:
                            new_cwd = os.path.join(cwd, target)
                        
                        # 规范化路径
                        new_cwd = os.path.normpath(new_cwd)
                    
                    # 验证目录是否存在
                    if os.path.isdir(new_cwd):
                        output = ""
                    else:
                        output = f"cd: {target}: No such file or directory\n"
                        new_cwd = cwd
                else:
                    # 执行普通命令
                    result = subprocess.run(
                        command,
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=30,
                        cwd=cwd,
                        env={**os.environ, "TERM": "xterm-256color", "LANG": "en_US.UTF-8"}
                    )
                    
                    output = result.stdout
                    if result.stderr:
                        output += result.stderr
                    
                    # 如果命令中包含cd，尝试获取新目录
                    if ' cd ' in command or command.startswith('cd '):
                        try:
                            pwd_result = subprocess.run(
                                f"cd {cwd} && {command} && pwd",
                                shell=True,
                                capture_output=True,
                                text=True,
                                timeout=5,
                                cwd=cwd
                            )
                            if pwd_result.returncode == 0:
                                lines = pwd_result.stdout.strip().split('\n')
                                if lines:
                                    potential_cwd = lines[-1]
                                    if os.path.isdir(potential_cwd):
                                        new_cwd = potential_cwd
                        except:
                            pass
                    
                    self.send_json(200, {
                        "success": True,
                        "output": output,
                        "exit_code": result.returncode if 'result' in dir() else 0,
                        "cwd": new_cwd
                    })
                    return
                
                # cd命令成功
                self.send_json(200, {
                    "success": True,
                    "output": output,
                    "exit_code": 0 if not output else 1,
                    "cwd": new_cwd
                })
                
            except subprocess.TimeoutExpired:
                self.send_json(408, {"error": "命令执行超时（30秒限制）"})
            except Exception as e:
                self.send_json(500, {"error": f"命令执行失败: {str(e)}"})
                
        except Exception as e:
            self.send_json(500, {"error": str(e)})

    def _handle_terminal_complete(self):
        """处理Tab补全请求"""
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            command = data.get("command", "")
            cwd = data.get("cwd", "/")
            cursor_pos = data.get("cursor_pos", 0)
            
            # 规范化工作目录
            cwd = os.path.normpath(cwd)
            if not os.path.isdir(cwd):
                cwd = "/"
            
            # 获取光标前的内容
            before_cursor = command[:cursor_pos]
            
            # 解析要补全的部分
            completions = []
            
            # 检查是否在补全路径
            parts = before_cursor.split()
            if not parts:
                # 补全命令
                completions = self._complete_command("")
            elif len(parts) == 1 and not before_cursor.endswith(' '):
                # 补全命令
                completions = self._complete_command(parts[0])
            else:
                # 补全路径或参数
                last_part = parts[-1] if not before_cursor.endswith(' ') else ""
                if last_part:
                    completions = self._complete_path(last_part, cwd)
            
            # 找到共同前缀
            common_prefix = ""
            if completions:
                common_prefix = completions[0]
                for c in completions[1:]:
                    while not c.startswith(common_prefix) and common_prefix:
                        common_prefix = common_prefix[:-1]
            
            self.send_json(200, {
                "success": True,
                "completions": completions[:20],  # 最多返回20个
                "common_prefix": common_prefix
            })
            
        except Exception as e:
            self.send_json(500, {"error": str(e)})
    
    def _complete_command(self, prefix):
        """补全命令"""
        try:
            # 获取PATH中的可执行文件
            paths = os.environ.get("PATH", "/usr/bin:/bin").split(":")
            commands = set()
            
            for path in paths:
                if os.path.isdir(path):
                    try:
                        for f in os.listdir(path):
                            full_path = os.path.join(path, f)
                            if os.path.isfile(full_path) and os.access(full_path, os.X_OK):
                                if f.startswith(prefix):
                                    commands.add(f)
                    except:
                        pass
            
            # 添加常用内置命令
            builtin = ['cd', 'ls', 'cat', 'grep', 'find', 'cp', 'mv', 'rm', 'mkdir', 
                      'rmdir', 'touch', 'echo', 'pwd', 'clear', 'exit', 'help',
                      'head', 'tail', 'less', 'more', 'wc', 'sort', 'uniq',
                      'chmod', 'chown', 'ln', 'df', 'du', 'free', 'top', 'ps',
                      'kill', 'jobs', 'bg', 'fg', 'export', 'source', 'alias',
                      'tar', 'gzip', 'gunzip', 'zip', 'unzip', 'curl', 'wget',
                      'systemctl', 'journalctl', 'docker', 'kubectl', 'git']
            
            for cmd in builtin:
                if cmd.startswith(prefix):
                    commands.add(cmd)
            
            return sorted(list(commands))[:20]
        except:
            return []
    
    def _complete_path(self, partial_path, cwd):
        """补全路径"""
        try:
            # 处理相对路径和绝对路径
            if partial_path.startswith('/'):
                base_dir = os.path.dirname(partial_path)
                prefix = os.path.basename(partial_path)
            elif partial_path.startswith('~'):
                home = os.path.expanduser('~')
                rest = partial_path[1:]
                if rest.startswith('/'):
                    base_dir = os.path.dirname(home + rest)
                    prefix = os.path.basename(home + rest)
                else:
                    base_dir = home
                    prefix = rest
            else:
                base_dir = os.path.dirname(os.path.join(cwd, partial_path))
                prefix = os.path.basename(partial_path)
            
            if not base_dir:
                base_dir = cwd if not partial_path.startswith('/') else '/'
            
            if not os.path.isdir(base_dir):
                return []
            
            completions = []
            for f in os.listdir(base_dir):
                if f.startswith(prefix):
                    full_path = os.path.join(base_dir, f)
                    # 添加/标记目录
                    if os.path.isdir(full_path):
                        completions.append(f + '/')
                    else:
                        completions.append(f)
            
            return sorted(completions)[:20]
        except:
            return []


if __name__ == "__main__":
    server = http.server.HTTPServer((SERVER_HOST, SERVER_PORT), FileViewerHandler)
    print(f"File viewer backend listening on {SERVER_HOST}:{SERVER_PORT}")
    server.serve_forever()
