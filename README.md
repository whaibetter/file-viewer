# File Viewer

基于 Web 的 Linux 服务器文件管理工具，支持文件浏览、编辑、上传、下载、删除（白名单管控）等功能。

## 功能特性

- **文件浏览** - 浏览服务器上的任意目录和文件
- **文件排序** - 支持按名称、大小、类型、所有者排序，文件夹优先显示
- **类型显示** - 中文友好显示文件类型（文件夹、Python、文本文件等）
- **快捷路径** - 自定义快捷访问路径，方便快速导航
- **文件编辑** - 在线编辑文本文件，自动备份
- **新建文件/文件夹** - 快速创建新文件或目录
- **文件上传** - 支持拖拽上传，自动重命名冲突文件
- **文件下载** - 支持单文件下载和批量打包下载
- **文件删除** - 支持白名单管控，防止误删系统重要文件
- **权限管理** - 查看和修改文件权限
- **系统监控** - 实时查看 CPU、内存、磁盘、网络状态
- **URL 历史** - 支持浏览器前进/后退导航
- **YAML 配置** - 统一配置管理，无需修改代码

## 环境要求

- Python 3.8+
- PyYAML (`pip install pyyaml`)
- Nginx（用于反向代理和静态文件服务）
- systemd（用于服务管理）

## 快速安装

```bash
# 1. 下载项目
git clone <repo-url> /opt/file-viewer
cd /opt/file-viewer

# 2. 安装依赖
pip install pyyaml

# 3. 运行安装脚本
sudo ./install.sh

# 4. 修改默认密码
sudo file-viewer passwd
```

安装完成后访问 `http://<服务器IP>` 即可使用。

## 文件结构

```
file-viewer/
├── config.yaml              # YAML 配置文件
├── file-viewer              # 管理脚本
├── file-viewer-server.py    # 后端服务 (Python)
├── file-viewer.service      # systemd 服务配置
├── index.html               # 前端页面
├── install.sh               # 安装脚本
└── README.md                # 说明文档

# 系统文件（安装后生成）
/etc/file-viewer/
├── config.yaml              # 系统配置文件（可选）
/etc/file-viewer.passwd      # 密码文件
/etc/file-viewer-whitelist.json  # 删除白名单
```

## 配置说明

### YAML 配置文件

配置文件位置（按优先级）：
1. `/etc/file-viewer/config.yaml` - 系统配置
2. `./config.yaml` - 项目目录配置

```yaml
# 服务器配置
server:
  host: "127.0.0.1"
  port: 9001
  session_timeout: 3600  # 会话超时时间（秒）

# 数据存储路径
storage:
  password_file: "/etc/file-viewer.passwd"
  whitelist_file: "/etc/file-viewer-whitelist.json"

# 删除白名单 - 只允许删除这些路径下的文件
delete_whitelist:
  - "/tmp"
  - "/var/tmp"
  - "/var/www/uploads"  # 可添加更多路径

# 文件夹权限配置
folder_permissions:
  "/var/www/html":
    read: true
    write: true
  "/etc/nginx":
    read: true
    write: true
  "/etc":
    read: true
    write: false

# 默认权限
default_permissions:
  read: true
  write: true

# 下载限制配置
download_limits:
  max_single_file_size: 104857600    # 单文件最大 100MB
  max_total_download_size: 209715200 # 批量下载最大 200MB
  max_files_in_zip: 500              # ZIP 最多 500 个文件
  max_dir_depth: 20                  # 目录最大深度
  max_file_preview_size: 2097152     # 文件预览最大 2MB
```

### 删除白名单管理

删除功能采用白名单机制，只有在白名单中的路径才能被删除：

1. **Web 界面管理**：登录后点击右上角"设置"按钮，在"删除白名单"标签页管理
2. **手动编辑**：修改配置文件中的 `delete_whitelist` 列表
3. **白名单规则**：
   - 白名单中的路径及其子目录都可以被删除
   - 非白名单路径不显示删除按钮

### 快捷路径管理

快捷路径用于快速访问常用目录，支持自定义配置：

1. **Web 界面管理**：登录后点击右上角"设置"按钮，在"快捷路径"标签页管理
2. **添加路径**：输入路径和显示名称，点击添加
3. **删除路径**：点击对应路径的删除按钮
4. **恢复默认**：点击"恢复默认快捷路径"按钮重置
5. **数据存储**：快捷路径配置保存在浏览器 localStorage 中

## 管理命令

```bash
file-viewer start      # 启动服务
file-viewer stop       # 停止服务
file-viewer restart    # 重启服务
file-viewer status     # 查看状态
file-viewer enable     # 设置开机自启
file-viewer disable    # 取消开机自启
file-viewer passwd     # 修改登录密码
file-viewer logs       # 查看日志
file-viewer logs -f    # 实时查看日志
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

## 安全建议

1. **修改默认密码** - 首次安装后立即运行 `file-viewer passwd`
2. **配置删除白名单** - 只添加必要的临时目录或上传目录
3. **限制写入权限** - 在配置文件中限制敏感目录的写入权限
4. **使用 HTTPS** - 配置 SSL 证书加密传输
5. **限制访问 IP** - 在 Nginx 中配置 IP 白名单

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/login` | POST | 登录认证 |
| `/api/logout` | POST | 退出登录 |
| `/api/auth/check` | GET | 检查登录状态 |
| `/api/file` | GET | 获取文件/目录内容 |
| `/api/file/save` | POST | 保存文件 |
| `/api/file/create` | POST | 新建文件/目录 |
| `/api/file/delete` | POST | 删除文件（需白名单） |
| `/api/file/chmod` | POST | 修改权限 |
| `/api/file/upload` | POST | 上传文件 |
| `/api/file/download` | GET | 单文件下载 |
| `/api/file/download/batch` | POST | 批量下载 |
| `/api/whitelist` | POST | 白名单管理 |
| `/api/system` | GET | 获取系统监控信息 |

## 常见问题

**Q: 登录后显示 401 错误？**

A: 检查密码文件 `/etc/file-viewer.passwd` 是否存在，重新设置密码。

**Q: 无法编辑/上传文件？**

A: 检查配置文件中的 `folder_permissions` 和 `default_permissions` 设置。

**Q: 删除按钮不显示？**

A: 该路径不在删除白名单中，请在"删除白名单"页面添加允许删除的路径。

**Q: 修改配置后不生效？**

A: 重启服务：`file-viewer restart`

**Q: 如何查看日志？**

```bash
journalctl -u file-viewer -f
```

## License

MIT License