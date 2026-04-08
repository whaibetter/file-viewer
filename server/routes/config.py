"""
配置路由模块
"""

import yaml
from flask import Blueprint, request, jsonify

from ..session import require_auth
from ..auth import (
    get_quick_paths,
    save_quick_paths,
    change_password,
)
from ..config import (
    get_user_config,
    save_user_config,
    get_effective_config,
    SESSION_TIMEOUT,
    DEFAULT_PERMISSIONS,
    MAX_SINGLE_FILE_SIZE,
    MAX_TOTAL_DOWNLOAD_SIZE,
    MAX_FILES_IN_ZIP,
    MAX_DIR_DEPTH,
    MAX_FILE_PREVIEW_SIZE,
    USER_CONFIG_FILE,
)

# 创建蓝图
config_bp = Blueprint('config', __name__, url_prefix='/api')


# === 快捷路径 ===
@config_bp.route('/quickpaths', methods=['GET'])
def quickpaths_get():
    """获取快捷路径"""
    if not require_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify({'quick_paths': get_quick_paths()})


@config_bp.route('/quickpaths', methods=['POST'])
def quickpaths_save():
    """保存快捷路径"""
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


# === 修改密码 ===
@config_bp.route('/changepwd', methods=['POST'])
def changepwd():
    """修改密码"""
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
@config_bp.route('/userconfig', methods=['GET'])
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


@config_bp.route('/userconfig', methods=['POST'])
def userconfig_save():
    """保存用户配置"""
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
            return jsonify({'success': True, 'config': user_cfg})
        else:
            return jsonify({'error': '保存配置失败'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@config_bp.route('/userconfig/reset', methods=['POST'])
def userconfig_reset():
    """重置用户配置为默认值"""
    if not require_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        if save_user_config({}):
            return jsonify({'success': True, 'message': '配置已重置为默认值'})
        else:
            return jsonify({'error': '重置配置失败'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@config_bp.route('/userconfig/raw', methods=['GET'])
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


@config_bp.route('/userconfig/raw', methods=['POST'])
def userconfig_raw_save():
    """保存原始配置文件内容"""
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
        from ..config import _user_config
        _user_config = parsed

        return jsonify({'success': True, 'message': '配置文件已保存'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500