# File Viewer

基于 Web 的 Linux 服务器文件管理工具，支持文件浏览、编辑、上传、权限管理等功能。

## 功能特性

- **文件浏览** - 浏览服务器上的任意目录和文件
- **文件编辑** - 在线编辑文本文件，自动备份
- **新建文件/文件夹** - 快速创建新文件或目录
- **文件上传** - 支持拖拽上传，自动重命名冲突文件
- **权限管理** - 查看和修改文件权限
- **系统监控** - 实时查看 CPU、内存、磁盘、网络状态
- **URL 历史** - 支持浏览器前进/后退导航
- **文件夹权限控制** - 可配置不同目录的读写权限

## 环境要求

- Python 3.8+
- Nginx（用于反向代理和静态文件服务）
- systemd（用于服务管理）

## 快速安装

```bash
# 1. 下载项目
git clone <repo-url> /opt/file-viewer
cd /opt/file-viewer

# 2. 运行安装脚本
sudo ./install.sh

# 3. 修改默认密码
sudo file-viewer passwd
```

安装完成后访问 `http://<服务器IP>` 即可使用。

## 文件结构

```
file-viewer/
├── file-viewer              # 管理脚本
├── file-viewer-server.py    # 后端服务 (Python)
├── file-viewer.service      # systemd 服务配置
├── index.html               # 前端页面
├── install.sh               # 安装脚本
└── README.md                # 说明文档
```

## 管理命令

```bash
file-viewer start      # 启动服务
file-viewer stop       # 停止服务
file-viewer restart    # 重启服务
file-viewer status     # 查看状态
file-viewer enable     # 设置开机自启
file-viewer disable    # 取消开机自启
file-viewer passwd     # 修改登录密码
```

## Nginx 配置

后端服务运行在 `127.0.0.1:9001`，需要 Nginx 反向代理：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    root /var/www/html;
    index index.html;

    # API 代理
    location /api/ {
        proxy_pass http://127.0.0.1:9001;
        proxy_set_header Host $host;
        proxy_read_timeout 30s;
    }

    # 静态文件
    location / {
        try_files $uri $uri/ =404;
    }
}
```

## 权限配置

编辑 `file-viewer-server.py` 中的 `FOLDER_PERMISSIONS` 配置：

```python
FOLDER_PERMISSIONS = {
    "/var/www/html": {"read": True, "write": True, "delete": False},
    "/etc/nginx": {"read": True, "write": True, "delete": False},
    "/etc": {"read": True, "write": False, "delete": False},
}

# 默认权限
DEFAULT_PERMISSIONS = {"read": True, "write": True, "delete": False}
```

权限说明：
- `True` - 允许操作
- `False` - 禁止操作
- 配置会匹配最长的路径前缀

## 安全建议

1. **修改默认密码** - 首次安装后立即运行 `file-viewer passwd`
2. **限制写入权限** - 只对必要的目录开启写入权限
3. **使用 HTTPS** - 配置 SSL 证书加密传输
4. **限制访问 IP** - 在 Nginx 中配置 IP 白名单

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/login` | POST | 登录认证 |
| `/api/logout` | POST | 退出登录 |
| `/api/auth/check` | GET | 检查登录状态 |
| `/api/file` | GET | 获取文件/目录内容 |
| `/api/file/save` | POST | 保存文件 |
| `/api/file/create` | POST | 新建文件/目录 |
| `/api/file/chmod` | POST | 修改权限 |
| `/api/file/upload` | POST | 上传文件 |
| `/api/system` | GET | 获取系统监控信息 |

## 常见问题

**Q: 登录后显示 401 错误？**

A: 检查密码文件 `/etc/file-viewer.passwd` 是否存在，重新设置密码。

**Q: 无法编辑/上传文件？**

A: 检查 `FOLDER_PERMISSIONS` 配置是否允许写入，以及文件系统权限。

**Q: 如何查看日志？**

```bash
journalctl -u file-viewer -f
```

## License

MIT License
