"""
监控历史数据存储模块
"""

import time
from collections import deque
from threading import Lock

def get_max_history_points():
    """获取最大历史数据点数"""
    try:
        from .config import MONITOR_HISTORY_MINUTES
        # 每分钟保存一个点，所以分钟数就是最大点数
        # 前端默认3秒刷新，所以实际保存的点数 = 分钟数 * 20
        return MONITOR_HISTORY_MINUTES * 20
    except Exception:
        # 默认60分钟，每3秒一个点 = 60 * 20 = 1200个点
        return 1200

# 初始最大历史数据点数
MAX_HISTORY_POINTS = get_max_history_points()

# 使用 deque 存储历史数据，自动丢弃旧数据
history_lock = Lock()

# 各项指标的历史数据（在模块加载时初始化）
def _init_history():
    """初始化历史数据存储"""
    global history, MAX_HISTORY_POINTS
    MAX_HISTORY_POINTS = get_max_history_points()
    history = {
        'cpu_usage': deque(maxlen=MAX_HISTORY_POINTS),
        'memory_usage': deque(maxlen=MAX_HISTORY_POINTS),
        'network_rx_rate': deque(maxlen=MAX_HISTORY_POINTS),
        'network_tx_rate': deque(maxlen=MAX_HISTORY_POINTS),
        'disk_io_read': deque(maxlen=MAX_HISTORY_POINTS),
        'disk_io_write': deque(maxlen=MAX_HISTORY_POINTS),
        'disk_iops': deque(maxlen=MAX_HISTORY_POINTS),
        'temperature': deque(maxlen=MAX_HISTORY_POINTS),
        'timestamps': deque(maxlen=MAX_HISTORY_POINTS),
    }
    return history

# 初始化历史数据
history = _init_history()


def add_history_point(data: dict):
    """添加一个历史数据点"""
    with history_lock:
        timestamp = int(time.time())
        
        # CPU 使用率
        if 'cpu' in data and 'usage_percent' in data['cpu']:
            history['cpu_usage'].append(data['cpu']['usage_percent'])
        
        # 内存使用率
        if 'memory' in data and 'usage_percent' in data['memory']:
            history['memory_usage'].append(data['memory']['usage_percent'])
        
        # 网络速率
        if 'network' in data:
            rx_rate = data['network'].get('rx_rate', 0)
            tx_rate = data['network'].get('tx_rate', 0)
            history['network_rx_rate'].append(rx_rate)
            history['network_tx_rate'].append(tx_rate)
        
        # 磁盘 IO
        if 'disk_io' in data:
            read_rate = data['disk_io'].get('read_bytes_per_sec', 0)
            write_rate = data['disk_io'].get('write_bytes_per_sec', 0)
            iops = data['disk_io'].get('iops', 0)
            history['disk_io_read'].append(read_rate)
            history['disk_io_write'].append(write_rate)
            history['disk_iops'].append(iops)
        
        # 温度
        temp = data.get('temperature')
        history['temperature'].append(temp if temp is not None else 0)
        
        # 时间戳
        history['timestamps'].append(timestamp)


def get_history(hours: int = 1) -> dict:
    """获取指定时间范围内的历史数据
    
    Args:
        hours: 小时数，支持 1、6、24 小时
    """
    with history_lock:
        # 计算需要的数据点数量
        # 假设每分钟一个点
        points_needed = hours * 60
        
        # 转换为列表
        result = {
            'cpu_usage': list(history['cpu_usage'])[-points_needed:],
            'memory_usage': list(history['memory_usage'])[-points_needed:],
            'network_rx_rate': list(history['network_rx_rate'])[-points_needed:],
            'network_tx_rate': list(history['network_tx_rate'])[-points_needed:],
            'disk_io_read': list(history['disk_io_read'])[-points_needed:],
            'disk_io_write': list(history['disk_io_write'])[-points_needed:],
            'disk_iops': list(history['disk_iops'])[-points_needed:],
            'temperature': list(history['temperature'])[-points_needed:],
            'timestamps': list(history['timestamps'])[-points_needed:],
        }
        
        return result


def clear_history():
    """清空历史数据"""
    with history_lock:
        for key in history:
            history[key].clear()
