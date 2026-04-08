"""
系统信息收集模块
"""

import os
import re
import time
import subprocess
from typing import Optional


def _read_file(path: str, default: str = "") -> str:
    """读取文件内容"""
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return default


def _run(cmd: str) -> str:
    """执行shell命令"""
    try:
        return subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL, timeout=5).decode().strip()
    except Exception:
        return ""


# 上一次网络统计
_prev_net = {"time": 0, "rx": 0, "tx": 0}


def collect_system_info() -> dict:
    """收集系统信息"""
    info = {}

    # 主机名
    info["hostname"] = _read_file("/etc/hostname", "unknown")

    # 内核版本
    info["kernel"] = _read_file("/proc/version").split(" ")[:3]
    info["kernel"] = " ".join(info["kernel"]) if info["kernel"] else ""

    # 操作系统
    os_release = _read_file("/etc/os-release")
    m = re.search(r'PRETTY_NAME="([^"]+)"', os_release)
    info["os"] = m.group(1) if m else "Linux"

    # 运行时间
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

    # 负载
    try:
        load = _read_file("/proc/loadavg").split()[:3]
        info["load"] = {"1m": float(load[0]), "5m": float(load[1]), "15m": float(load[2])}
    except Exception:
        info["load"] = {"1m": 0, "5m": 0, "15m": 0}

    # CPU信息
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

    # CPU使用率
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

    # 内存信息
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

    # 磁盘信息
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

    # 网络信息
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

    # 进程信息
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

    # 温度
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
    from .config import MAX_FILES_IN_ZIP, MAX_TOTAL_DOWNLOAD_SIZE

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