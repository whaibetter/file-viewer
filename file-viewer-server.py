#!/usr/bin/env python3
"""
File Viewer Backend Service with Authentication
Provides an API to read local files and return their content.
Runs on localhost:9001 (only accessible via nginx reverse proxy)
"""

import http.server
import json
import os
import urllib.parse
import hashlib
import time
import secrets
import hmac
import subprocess
import re
import pwd
import grp
from pathlib import Path


# === Configuration ===
SESSION_TIMEOUT = 3600  # seconds
SECRET_KEY = secrets.token_bytes(32)
PASSWORD_FILE = Path("/etc/file-viewer.passwd")

# 文件夹操作权限配置
# 格式: {"路径": {"read": bool, "write": bool, "delete": bool}}
# 使用 None 表示允许所有操作，False 表示禁止，True 表示允许
FOLDER_PERMISSIONS = {
    # 示例配置：
    # "/etc": {"read": True, "write": False, "delete": False},
    # "/var/www/html": {"read": True, "write": True, "delete": True},
}
# 默认权限：允许读取和写入，禁止删除
DEFAULT_PERMISSIONS = {"read": True, "write": True, "delete": False}


def get_file_permissions(path: str) -> dict:
    """获取文件/目录的权限信息"""
    try:
        st = os.stat(path)
        mode = st.st_mode
        
        # 获取所有者和组
        try:
            owner = pwd.getpwuid(st.st_uid).pw_name
        except KeyError:
            owner = str(st.st_uid)
        try:
            group = grp.getgrgid(st.st_gid).gr_name
        except KeyError:
            group = str(st.st_gid)
        
        return {
            "mode": stat.filemode(mode),  # 如 "drwxr-xr-x"
            "octal": oct(stat.S_IMODE(mode)),  # 如 "0o755"
            "owner": owner,
            "group": group,
            "uid": st.st_uid,
            "gid": st.st_gid,
            "mtime": st.st_mtime,
        }
    except Exception as e:
        return {"error": str(e)}


def get_folder_permission_config(path: str) -> dict:
    """获取路径对应的权限配置"""
    # 查找最匹配的路径配置
    best_match = None
    best_len = 0
    
    for folder_path, perms in FOLDER_PERMISSIONS.items():
        if path.startswith(folder_path) and len(folder_path) > best_len:
            best_match = perms
            best_len = len(folder_path)
    
    return best_match if best_match else DEFAULT_PERMISSIONS


def check_permission(path: str, action: str) -> tuple[bool, str]:
    """检查是否允许对路径执行操作
    
    Args:
        path: 文件/目录路径
        action: 'read', 'write', 'delete'
    
    Returns:
        (allowed: bool, reason: str)
    """
    perms = get_folder_permission_config(path)
    
    if action in perms:
        if perms[action] is None:
            return True, "allowed"
        elif perms[action]:
            return True, "allowed"
        else:
            return False, f"{action} permission denied for this folder"
    else:
        # 默认行为
        if action == "read":
            return True, "allowed"
        else:
            return False, f"{action} permission denied by default"


def verify_password(password: str) -> bool:
    """Verify password against stored hash"""
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


# === Session Store ===
sessions = {}  # sid -> {"user": str, "expire": int}


def cleanup_sessions():
    now = int(time.time())
    expired = [sid for sid, sess in sessions.items() if sess["expire"] < now]
    for sid in expired:
        del sessions[sid]


def create_session(user: str) -> str:
    cleanup_sessions()
    sid = secrets.token_urlsafe(32)
    sessions[sid] = {
        "user": user,
        "expire": int(time.time()) + SESSION_TIMEOUT
    }
    return sid


def get_session(sid: str) -> dict | None:
    cleanup_sessions()
    sess = sessions.get(sid)
    if sess and sess["expire"] >= int(time.time()):
        return sess
    return None


def delete_session(sid: str):
    sessions.pop(sid, None)


# === System Info Collection ===

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


# Store previous network stats for rate calculation
_prev_net = {"time": 0, "rx": 0, "tx": 0}


def collect_system_info() -> dict:
    info = {}

    # ── Hostname & OS ──
    info["hostname"] = _read_file("/etc/hostname", "unknown")
    info["kernel"] = _read_file("/proc/version").split(" ")[:3]
    info["kernel"] = " ".join(info["kernel"]) if info["kernel"] else ""

    # Pretty OS name
    os_release = _read_file("/etc/os-release")
    m = re.search(r'PRETTY_NAME="([^"]+)"', os_release)
    info["os"] = m.group(1) if m else "Linux"

    # ── Uptime ──
    try:
        uptime_s = float(_read_file("/proc/uptime").split()[0])
        days = int(uptime_s // 86400)
        hours = int((uptime_s % 86400) // 3600)
        mins = int((uptime_s % 3600) // 60)
        parts = []
        if days > 0:
            parts.append(f"{days}天")
        if hours > 0:
            parts.append(f"{hours}小时")
        parts.append(f"{mins}分钟")
        info["uptime"] = " ".join(parts)
        info["uptime_seconds"] = int(uptime_s)
    except Exception:
        info["uptime"] = "N/A"
        info["uptime_seconds"] = 0

    # ── Load Average ──
    try:
        load = _read_file("/proc/loadavg").split()[:3]
        info["load"] = {"1m": float(load[0]), "5m": float(load[1]), "15m": float(load[2])}
    except Exception:
        info["load"] = {"1m": 0, "5m": 0, "15m": 0}

    # ── CPU ──
    try:
        cpuinfo = _read_file("/proc/cpuinfo")
        models = re.findall(r"model name\s*:\s*(.+)", cpuinfo)
        info["cpu"] = {
            "model": models[0].strip() if models else "Unknown",
            "cores": len(models),
            "threads": len(models),
        }
        # Physical cores (unique core ids)
        phys = set(re.findall(r"core id\s*:\s*(\d+)", cpuinfo))
        sockets = set(re.findall(r"physical id\s*:\s*(\d+)", cpuinfo))
        if phys and sockets:
            info["cpu"]["physical_cores"] = len(phys) * max(len(sockets), 1)
        else:
            info["cpu"]["physical_cores"] = info["cpu"]["cores"]
    except Exception:
        info["cpu"] = {"model": "Unknown", "cores": 0, "threads": 0, "physical_cores": 0}

    # CPU usage from /proc/stat (instantaneous snapshot vs previous)
    try:
        with open("/proc/stat") as f:
            line = f.readline()
        vals = list(map(int, line.split()[1:]))
        # user, nice, system, idle, iowait, irq, softirq, steal
        idle = vals[3] + vals[4]
        total = sum(vals[:8])

        if not hasattr(collect_system_info, "_prev_cpu"):
            collect_system_info._prev_cpu = (idle, total)
            # First call: use load average as estimate
            info["cpu"]["usage_percent"] = round(min(info["load"]["1m"] / max(info["cpu"]["cores"], 1) * 100, 100), 1)
        else:
            prev_idle, prev_total = collect_system_info._prev_cpu
            d_idle = idle - prev_idle
            d_total = total - prev_total
            if d_total > 0:
                info["cpu"]["usage_percent"] = round((1 - d_idle / d_total) * 100, 1)
            else:
                info["cpu"]["usage_percent"] = 0.0
            collect_system_info._prev_cpu = (idle, total)
    except Exception:
        info["cpu"]["usage_percent"] = 0.0

    # ── Memory ──
    try:
        meminfo = _read_file("/proc/meminfo")
        mem = {}
        for line in meminfo.splitlines():
            parts = line.split(":")
            if len(parts) == 2:
                key = parts[0].strip()
                val = int(parts[1].strip().split()[0])  # kB
                mem[key] = val
        total = mem.get("MemTotal", 0)
        available = mem.get("MemAvailable", 0)
        used = total - available
        swap_total = mem.get("SwapTotal", 0)
        swap_free = mem.get("SwapFree", 0)
        swap_used = swap_total - swap_free
        info["memory"] = {
            "total": total * 1024,
            "used": used * 1024,
            "available": available * 1024,
            "usage_percent": round(used / total * 100, 1) if total > 0 else 0,
            "swap_total": swap_total * 1024,
            "swap_used": swap_used * 1024,
            "swap_percent": round(swap_used / swap_total * 100, 1) if swap_total > 0 else 0,
            "buffers": mem.get("Buffers", 0) * 1024,
            "cached": mem.get("Cached", 0) * 1024,
        }
    except Exception:
        info["memory"] = {"total": 0, "used": 0, "available": 0, "usage_percent": 0,
                          "swap_total": 0, "swap_used": 0, "swap_percent": 0,
                          "buffers": 0, "cached": 0}

    # ── Disks ──
    try:
        df_out = _run("df -B1 -x tmpfs -x devtmpfs -x squashfs -x overlay 2>/dev/null")
        disks = []
        for line in df_out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 6 and parts[0].startswith("/"):
                total_b = int(parts[1])
                used_b = int(parts[2])
                avail_b = int(parts[3])
                mount = parts[5]
                disks.append({
                    "device": parts[0],
                    "mount": mount,
                    "total": total_b,
                    "used": used_b,
                    "available": avail_b,
                    "usage_percent": round(used_b / total_b * 100, 1) if total_b > 0 else 0,
                })
        info["disks"] = disks
    except Exception:
        info["disks"] = []

    # ── Network ──
    try:
        net_dev = _read_file("/proc/net/dev")
        interfaces = []
        total_rx = 0
        total_tx = 0
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
                # Get IP address
                ip = _run(f"ip -4 addr show {name} 2>/dev/null | grep -oP 'inet \\K[\\d.]+'")
                interfaces.append({
                    "name": name,
                    "ip": ip or "-",
                    "rx_bytes": rx,
                    "tx_bytes": tx,
                })

        # Calculate rates
        now = time.time()
        global _prev_net
        dt = now - _prev_net["time"] if _prev_net["time"] > 0 else 0
        if dt > 0:
            rx_rate = (total_rx - _prev_net["rx"]) / dt
            tx_rate = (total_tx - _prev_net["tx"]) / dt
        else:
            rx_rate = 0
            tx_rate = 0
        _prev_net = {"time": now, "rx": total_rx, "tx": total_tx}

        info["network"] = {
            "interfaces": interfaces,
            "rx_rate": max(0, rx_rate),
            "tx_rate": max(0, tx_rate),
        }
    except Exception:
        info["network"] = {"interfaces": [], "rx_rate": 0, "tx_rate": 0}

    # ── Top Processes (by CPU) ──
    try:
        ps_out = _run("ps aux --sort=-%cpu 2>/dev/null | head -11")
        procs = []
        for line in ps_out.splitlines()[1:]:
            parts = line.split(None, 10)
            if len(parts) >= 11:
                procs.append({
                    "user": parts[0],
                    "pid": int(parts[1]),
                    "cpu": float(parts[2]),
                    "mem": float(parts[3]),
                    "command": parts[10][:80],
                })
        info["processes"] = procs
    except Exception:
        info["processes"] = []

    # ── Temperature (optional) ──
    try:
        temp_paths = [
            "/sys/class/thermal/thermal_zone0/temp",
            "/sys/class/hwmon/hwmon0/temp1_input",
        ]
        for tp in temp_paths:
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


# === Request Handler ===
class FileViewerHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # suppress default logging

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

    def get_cookie(self, name: str) -> str | None:
        cookie_header = self.headers.get("Cookie", "")
        for cookie in cookie_header.split(";"):
            if "=" in cookie:
                k, v = cookie.strip().split("=", 1)
                if k == name:
                    return v
        return None

    def set_cookie(self, name: str, value: str, max_age: int = SESSION_TIMEOUT):
        cookie = f"{name}={value}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Strict"
        self.send_header("Set-Cookie", cookie)

    def require_auth(self) -> bool:
        """Check if user is authenticated. Send 401 if not."""
        sid = self.get_cookie("sessionid")
        if not sid or not get_session(sid):
            self.send_json(401, {"error": "Unauthorized"})
            return False
        return True

    def do_OPTIONS(self):
        """Handle CORS preflight"""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Cookie")
        self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        
        if parsed.path == "/api/login":
            # Login endpoint
            try:
                length = int(self.headers.get("Content-Length", 0))
                post_data = self.rfile.read(length)
                data = json.loads(post_data.decode("utf-8"))
                password = data.get("password", "")

                if verify_password(password):
                    sid = create_session("admin")
                    self.send_json(200, {"success": True}, {"Set-Cookie": f"sessionid={sid}; Path=/; Max-Age={SESSION_TIMEOUT}; HttpOnly; SameSite=Strict"})
                else:
                    self.send_json(401, {"error": "Invalid password"})
            except Exception:
                self.send_json(400, {"error": "Bad request"})
            return

        elif parsed.path == "/api/logout":
            # Logout endpoint
            if self.require_auth():
                sid = self.get_cookie("sessionid")
                if sid:
                    delete_session(sid)
                self.send_json(200, {"success": True}, {"Set-Cookie": "sessionid=; Path=/; Max-Age=0"})
            return

        elif parsed.path == "/api/file/save":
            # Save file endpoint
            if not self.require_auth():
                return
            self._handle_save_file()
            return

        elif parsed.path == "/api/file/create":
            # Create file/directory endpoint
            if not self.require_auth():
                return
            self._handle_create()
            return

        elif parsed.path == "/api/file/chmod":
            # Change permissions endpoint
            if not self.require_auth():
                return
            self._handle_chmod()
            return

        elif parsed.path == "/api/file/upload":
            # Upload file endpoint
            if not self.require_auth():
                return
            self._handle_upload()
            return

        self.send_json(404, {"error": "Not Found"})

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        # Login check endpoint (no auth required)
        if parsed.path == "/api/auth/check":
            sid = self.get_cookie("sessionid")
            sess = get_session(sid) if sid else None
            self.send_json(200, {"authenticated": bool(sess)})
            return

        # System monitor endpoint (auth required)
        if parsed.path == "/api/system":
            if not self.require_auth():
                return
            self.send_json(200, collect_system_info())
            return

        # File API (auth required)
        if parsed.path == "/api/file":
            if not self.require_auth():
                return
            self._handle_file(parsed)
            return

        self.send_json(404, {"error": "Not Found"})

    def _handle_file(self, parsed):

        params = urllib.parse.parse_qs(parsed.query)
        path_list = params.get("path", [])

        if not path_list:
            self.send_json(400, {"error": "Missing 'path' parameter"})
            return

        file_path = path_list[0]
        file_path = os.path.normpath(file_path)

        if not os.path.exists(file_path):
            self.send_json(404, {"error": f"File not found: {file_path}"})
            return

        # 检查读取权限
        allowed, reason = check_permission(file_path, "read")
        if not allowed:
            self.send_json(403, {"error": reason})
            return

        # 获取当前路径的权限配置
        folder_perms = get_folder_permission_config(file_path)

        if os.path.isdir(file_path):
            try:
                entries = []
                for name in sorted(os.listdir(file_path)):
                    full = os.path.join(file_path, name)
                    entry_perms = get_file_permissions(full)
                    entries.append({
                        "name": name,
                        "type": "dir" if os.path.isdir(full) else "file",
                        "size": os.path.getsize(full) if os.path.isfile(full) else None,
                        "permissions": entry_perms,
                    })
                self.send_json(200, {
                    "type": "directory",
                    "path": file_path,
                    "entries": entries,
                    "permissions": get_file_permissions(file_path),
                    "folder_permissions": folder_perms,
                })
            except PermissionError:
                self.send_json(403, {"error": "Permission denied"})
            return

        size = os.path.getsize(file_path)
        if size > 2 * 1024 * 1024:
            self.send_json(413, {"error": f"File too large ({size} bytes). Limit is 2 MB."})
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

            self.send_json(200, {
                "type": "file",
                "path": file_path,
                "size": size,
                "encoding": encoding,
                "content": file_content,
                "permissions": get_file_permissions(file_path),
                "folder_permissions": folder_perms,
            })
        except PermissionError:
            self.send_json(403, {"error": "Permission denied"})
        except OSError as e:
            self.send_json(500, {"error": str(e)})

    def _handle_save_file(self):
        """保存文件内容"""
        try:
            length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(length)
            data = json.loads(post_data.decode("utf-8"))
            
            file_path = data.get("path", "")
            file_content = data.get("content", "")
            
            if not file_path:
                self.send_json(400, {"error": "Missing 'path' parameter"})
                return
            
            file_path = os.path.normpath(file_path)
            
            # 检查写入权限
            allowed, reason = check_permission(file_path, "write")
            if not allowed:
                self.send_json(403, {"error": reason})
                return
            
            # 创建备份（如果文件存在）
            backup_path = file_path + ".bak"
            if os.path.exists(file_path):
                import shutil
                shutil.copy2(file_path, backup_path)
            
            # 写入文件
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(file_content)
            
            self.send_json(200, {
                "success": True,
                "path": file_path,
                "size": len(file_content.encode("utf-8")),
                "message": "File saved successfully"
            })
            
        except PermissionError:
            self.send_json(403, {"error": "Permission denied"})
        except OSError as e:
            self.send_json(500, {"error": str(e)})
        except Exception as e:
            self.send_json(400, {"error": f"Bad request: {str(e)}"})

    def _handle_create(self):
        """创建新文件或目录"""
        try:
            length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(length)
            data = json.loads(post_data.decode("utf-8"))
            
            parent_path = data.get("parent", "")
            name = data.get("name", "")
            item_type = data.get("type", "file")  # file 或 directory
            
            if not parent_path or not name:
                self.send_json(400, {"error": "Missing 'parent' or 'name' parameter"})
                return
            
            # 安全检查：防止路径遍历攻击
            name = os.path.basename(name)
            if not name or name.startswith('.'):
                self.send_json(400, {"error": "Invalid name"})
                return
            
            full_path = os.path.normpath(os.path.join(parent_path, name))
            
            # 检查写入权限
            allowed, reason = check_permission(full_path, "write")
            if not allowed:
                self.send_json(403, {"error": reason})
                return
            
            # 检查是否已存在
            if os.path.exists(full_path):
                self.send_json(409, {"error": f"{'File' if item_type == 'file' else 'Directory'} already exists"})
                return
            
            if item_type == "directory":
                os.makedirs(full_path, exist_ok=False)
                msg = "Directory created successfully"
            else:
                # 创建空文件
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write("")
                msg = "File created successfully"
            
            self.send_json(200, {
                "success": True,
                "path": full_path,
                "type": item_type,
                "message": msg
            })
            
        except PermissionError:
            self.send_json(403, {"error": "Permission denied"})
        except OSError as e:
            self.send_json(500, {"error": str(e)})
        except Exception as e:
            self.send_json(400, {"error": f"Bad request: {str(e)}"})

    def _handle_chmod(self):
        """修改文件/目录权限"""
        try:
            length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(length)
            data = json.loads(post_data.decode("utf-8"))
            
            file_path = data.get("path", "")
            mode = data.get("mode", "")  # 如 "755" 或 "0o755"
            
            if not file_path or not mode:
                self.send_json(400, {"error": "Missing 'path' or 'mode' parameter"})
                return
            
            file_path = os.path.normpath(file_path)
            
            # 检查写入权限
            allowed, reason = check_permission(file_path, "write")
            if not allowed:
                self.send_json(403, {"error": reason})
                return
            
            # 解析权限模式
            if isinstance(mode, int):
                mode_int = mode
            elif mode.startswith("0o"):
                mode_int = int(mode, 8)
            else:
                mode_int = int(mode, 8)
            
            # 修改权限
            os.chmod(file_path, mode_int)
            
            self.send_json(200, {
                "success": True,
                "path": file_path,
                "mode": oct(mode_int),
                "message": "Permissions changed successfully"
            })
            
        except PermissionError:
            self.send_json(403, {"error": "Permission denied"})
        except OSError as e:
            self.send_json(500, {"error": str(e)})
        except Exception as e:
            self.send_json(400, {"error": f"Bad request: {str(e)}"})

    def _handle_upload(self):
        """上传文件"""
        try:
            import cgi
            import shutil
            
            content_type = self.headers.get("Content-Type", "")
            if "multipart/form-data" not in content_type:
                self.send_json(400, {"error": "Content-Type must be multipart/form-data"})
                return
            
            # 解析表单数据
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": content_type
                }
            )
            
            # 获取目标目录
            dest_dir = form.getvalue("path", "")
            if not dest_dir:
                self.send_json(400, {"error": "Missing 'path' parameter"})
                return
            
            dest_dir = os.path.normpath(dest_dir)
            
            # 检查写入权限
            allowed, reason = check_permission(dest_dir, "write")
            if not allowed:
                self.send_json(403, {"error": reason})
                return
            
            # 获取上传的文件
            file_item = form["file"]
            if not file_item.filename:
                self.send_json(400, {"error": "No file uploaded"})
                return
            
            # 安全处理文件名
            filename = os.path.basename(file_item.filename)
            dest_path = os.path.join(dest_dir, filename)
            
            # 检查是否已存在
            if os.path.exists(dest_path):
                # 自动重命名
                base, ext = os.path.splitext(filename)
                counter = 1
                while os.path.exists(dest_path):
                    filename = f"{base}_{counter}{ext}"
                    dest_path = os.path.join(dest_dir, filename)
                    counter += 1
            
            # 保存文件
            with open(dest_path, "wb") as f:
                shutil.copyfileobj(file_item.file, f)
            
            file_size = os.path.getsize(dest_path)
            
            self.send_json(200, {
                "success": True,
                "path": dest_path,
                "filename": filename,
                "size": file_size,
                "message": "File uploaded successfully"
            })
            
        except PermissionError:
            self.send_json(403, {"error": "Permission denied"})
        except OSError as e:
            self.send_json(500, {"error": str(e)})
        except Exception as e:
            self.send_json(400, {"error": f"Bad request: {str(e)}"})


if __name__ == "__main__":
    server = http.server.HTTPServer(("127.0.0.1", 9001), FileViewerHandler)
    print("File viewer backend listening on 127.0.0.1:9001")
    print(f"Password file: {PASSWORD_FILE}")
    server.serve_forever()
