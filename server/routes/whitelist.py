"""
白名单路由模块
"""

import os
from flask import Blueprint, request, jsonify

from ..session import require_auth
from ..auth import (
    load_whitelist,
    save_whitelist,
    format_whitelist_with_types,
)

# 创建蓝图
whitelist_bp = Blueprint('whitelist', __name__, url_prefix='/api/whitelist')


@whitelist_bp.route('', methods=['GET', 'POST', 'DELETE', 'PUT'])
@whitelist_bp.route('/', methods=['GET', 'POST', 'DELETE', 'PUT'])
def whitelist():
    """白名单管理"""
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