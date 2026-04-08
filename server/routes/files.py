"""
文件操作路由模块
"""

import os
import shutil
import zipfile
import io
from pathlib import Path
from flask import Blueprint, request, jsonify, send_from_directory, Response

from ..config import (
    PROJECT_DIR,
    MAX_FILE_PREVIEW_SIZE,
    MAX_SINGLE_FILE_SIZE,
    MAX_TOTAL_DOWNLOAD_SIZE,
    MAX_FILES_IN_ZIP,
)
from ..session import create_session, delete_session, get_cookie, require_auth
from ..auth import (
    check_permission,
    get_file_permissions,
    get_folder_permission_config,
    is_in_whitelist,
    verify_password,
)

# 创建蓝图
files_bp = Blueprint('files', __name__)


@files_bp.route('/')
@files_bp.route('/index.html')
def index():
    """主页"""
    index_path = PROJECT_DIR / 'index.html'
    if index_path.exists():
        with open(index_path, 'r', encoding='utf-8') as f:
            return f.read(), 200, {'Content-Type': 'text/html; charset=utf-8'}
    return jsonify({'error': 'index.html not found'}), 404


@files_bp.route('/api/login', methods=['POST'])
def login():
    """登录"""
    try:
        data = request.json
        password = data.get('password', '')
        if verify_password(password):
            sid = create_session('admin')
            response = jsonify({'success': True})
            response.set_cookie('sessionid', sid, max_age=3600, httponly=True, samesite='Lax')
            return response
        else:
            return jsonify({'error': 'Invalid password'}), 401
    except Exception as e:
        return jsonify({'error': 'Bad request'}), 400


@files_bp.route('/api/logout', methods=['POST'])
def logout():
    """登出"""
    sid = get_cookie('sessionid')
    if sid:
        delete_session(sid)
    response = jsonify({'success': True})
    response.set_cookie('sessionid', '', max_age=0)
    return response


@files_bp.route('/api/auth/check', methods=['GET'])
def auth_check():
    """检查认证状态"""
    sid = get_cookie('sessionid')
    from ..session import get_session
    return jsonify({'authenticated': bool(get_session(sid))})


@files_bp.route('/api/system', methods=['GET'])
def system():
    """系统信息"""
    if not require_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    from ..system import collect_system_info
    return jsonify(collect_system_info())


@files_bp.route('/api/file', methods=['GET'])
def file_info():
    """获取文件/目录信息"""
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


@files_bp.route('/api/file/save', methods=['POST'])
def file_save():
    """保存文件"""
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


@files_bp.route('/api/file/create', methods=['POST'])
def file_create():
    """创建文件/目录"""
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


@files_bp.route('/api/file/delete', methods=['POST'])
def file_delete():
    """删除文件/目录"""
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


@files_bp.route('/api/file/rename', methods=['POST'])
def file_rename():
    """重命名文件/目录"""
    if not require_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        data = request.json
        old_path = data.get('path', '')
        new_name = data.get('new_name', '')

        if not old_path:
            return jsonify({'error': "Missing 'path' parameter"}), 400
        if not new_name:
            return jsonify({'error': "Missing 'new_name' parameter"}), 400

        # 验证新名称不包含路径分隔符
        if '/' in new_name or '\\' in new_name:
            return jsonify({'error': 'New name cannot contain path separators'}), 400

        old_path = os.path.normpath(old_path)
        if not os.path.exists(old_path):
            return jsonify({'error': 'File or directory not found'}), 404

        # 检查写入权限
        allowed, reason = check_permission(old_path, 'write')
        if not allowed:
            return jsonify({'error': reason}), 403

        # 构建新路径
        parent = os.path.dirname(old_path)
        new_path = os.path.join(parent, new_name)

        # 检查目标是否已存在
        if os.path.exists(new_path):
            return jsonify({'error': 'File or directory already exists'}), 400

        # 执行重命名
        os.rename(old_path, new_path)

        return jsonify({
            'success': True,
            'old_path': old_path,
            'new_path': new_path,
            'new_name': new_name
        })
    except PermissionError:
        return jsonify({'error': 'Permission denied'}), 403
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@files_bp.route('/api/file/chmod', methods=['POST'])
def file_chmod():
    """修改文件权限"""
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


@files_bp.route('/api/file/upload', methods=['POST'])
def file_upload():
    """上传文件"""
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


@files_bp.route('/api/file/download', methods=['GET'])
def file_download():
    """下载文件"""
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
        import tempfile
        import urllib.parse
        dirname = os.path.basename(path) or 'root'

        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
            tmp_path = tmp.name

        with zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(path):
                for file in files:
                    file_full = os.path.join(root, file)
                    arcname = os.path.relpath(file_full, os.path.dirname(path))
                    zf.write(file_full, arcname)

        return send_from_directory(os.path.dirname(tmp_path), os.path.basename(tmp_path), as_attachment=True, download_name=f"{dirname}.zip")

    else:
        import urllib.parse
        filename = os.path.basename(path)
        return send_from_directory(os.path.dirname(path), filename, as_attachment=True)


@files_bp.route('/api/file/download/batch', methods=['POST'])
def batch_download():
    """批量下载"""
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

        return send_from_directory(os.path.dirname(tmp_path), os.path.basename(tmp_path), as_attachment=True, download_name="download.zip")
    except Exception as e:
        return jsonify({'error': str(e)}), 500