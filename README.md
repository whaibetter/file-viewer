# File Viewer

基于 Web 的 Linux 服务器文件管理工具，支持文件浏览、编辑、上传、下载、删除等功能。

## 功能特性

### 文件管理
- **文件浏览** - 浏览服务器上的任意目录和文件
- **文件排序** - 支持按名称、大小、类型、所有者排序，文件夹优先显示
- **类型显示** - 中文友好显示文件类型（文件夹、Python、文本文件等）
- **快捷路径** - 自定义快捷访问路径，方便快速导航
- **文件编辑** - 在线编辑文本文件，自动备份
- **新建文件/文件夹** - 快速创建新文件或目录
- **重命名** - 支持重命名文件和文件夹，自动校验名称合法性
- **文件上传** - 支持拖拽上传，自动重命名冲突文件
- **文件下载** - 支持单文件下载和批量打包下载
- **文件删除** - 支持白名单管控，防止误删系统重要文件
- **权限管理** - 查看和修改文件权限

### 系统监控
- **实时监控** - CPU、内存、磁盘、网络状态实时展示
- **进程管理** - 查看系统进程列表和资源占用

### 工具中心
- **OCR 文字识别** - 支持图片文字识别，多种模型可选
  - 三种识别模式：OCR文字识别、Markdown格式、纯文本提取
  - 支持 DeepSeek-OCR、Qwen2-VL 等多种模型
  - 可折叠调试面板，显示请求/响应参数

### 系统配置
- **用户配置** - Web 界面管理白名单、快捷路径等配置
- **URL 历史** - 支持浏览器前进/后退导航
- **YAML 配置** - 统一配置管理，无需修改代码

## 环境要求

- Python 3.8+
- PyYAML (`pip install pyyaml`)
- Flask (`pip install flask`)
- Flask-SocketIO (`pip install flask-socketio`)
- systemd（用于服务管理）
- Nginx（推荐，用于反向代理）

## 快速安装

```bash
# 1. 克隆项目
git clone https://github.com/whaibetter/file-viewer.git /home/file-viewer
cd /home/file-viewer

# 2. 安装依赖
pip install pyyaml flask flask-socketio

# 3. 运行安装脚本
sudo ./install.sh

# 4. 修改默认密码
sudo file-viewer passwd
```

安装完成后访问 `http://<服务器IP>` 即可使用。

## 开发模式

服务直接运行项目目录中的代码，修改前后端代码后只需重启即可：

```bash
# 修改 index.html 或 file-viewer-server.py 后
sudo file-viewer restart
```

无需复制文件，重启即生效。

## 文件结构

```
/home/file-viewer/           # 项目目录（服务直接读取）
├── config.yaml              # 配置文件
├── file-viewer              # 管理脚本
├── file-viewer-server.py    # 后端服务
├── file-viewer.service      # systemd 服务配置
├── index.html               # 前端页面
├── install.sh               # 安装脚本
└── README.md                # 说明文档

/etc/file-viewer/            # 系统数据目录
├── config.yaml              # 用户配置（可选）
├── passwd                   # 密码文件
└── ai_config.json           # AI/OCR 配置
```

## 配置说明

### 配置存储位置

| 配置项 | 配置路径 | 说明 |
|--------|----------|------|
| 主配置 | `/home/file-viewer/config.yaml` | 项目目录 |
| 用户配置 | `/etc/file-viewer/config.yaml` | 覆盖主配置（可选） |
| 密码文件 | `/etc/file-viewer/passwd` | SHA256哈希存储 |
| AI配置 | `/etc/file-viewer/ai_config.json` | OCR API配置 |

### YAML 配置文件

```yaml
# File Viewer 主配置文件

# 服务器配置
server:
  host: "127.0.0.1"
  port: 9001
  session_timeout: 3600

# 数据存储配置
storage:
  config_dir: "/etc/file-viewer"
  password_file: "/etc/file-viewer/passwd"

# 安全配置
security:
  delete_whitelist:
    - "/tmp"
    - "/var/tmp"
    - "/var/www/uploads"

# 界面配置
ui:
  quick_paths:
    - { path: "/", name: "/ 根目录" }
    - { path: "/etc", name: "/etc" }
    - { path: "/var/log", name: "/var/log" }

# 权限配置
permissions:
  folder_permissions:
    "/var/www/html":
      read: true
      write: true
    "/etc":
      read: true
      write: false
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

### Web 设置面板

登录后点击右上角"设置"按钮，可管理以下配置：

| 标签页 | 功能 |
|--------|------|
| 删除白名单 | 添加/删除允许删除的路径 |
| 快捷路径 | 自定义文件浏览页面的快捷按钮 |
| 系统配置 | 会话超时、默认权限、下载限制等 |
| 密码修改 | 修改登录密码 |

## 管理命令

```bash
file-viewer start      # 启动服务
file-viewer stop       # 停止服务
file-viewer restart    # 重启服务（加载最新代码）
file-viewer status     # 查看状态
file-viewer enable     # 设置开机自启
file-viewer disable    # 取消开机自启
file-viewer passwd     # 修改登录密码
file-viewer logs       # 查看日志
file-viewer logs -f    # 实时查看日志
```

## Nginx 配置（推荐）

后端服务运行在 `127.0.0.1:9001`，需要 Nginx 反向代理：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # API 代理
    location /api/ {
        proxy_pass http://127.0.0.1:9001;
        proxy_set_header Host $host;
        proxy_read_timeout 30s;
    }

    # 前端页面
    location / {
        proxy_pass http://127.0.0.1:9001;
        proxy_set_header Host $host;
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

### 认证相关
| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/login` | POST | 登录认证 |
| `/api/logout` | POST | 退出登录 |
| `/api/auth/check` | GET | 检查登录状态 |

### 文件操作
| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/file` | GET | 获取文件/目录内容 |
| `/api/file/save` | POST | 保存文件 |
| `/api/file/create` | POST | 新建文件/目录 |
| `/api/file/rename` | POST | 重命名文件/目录 |
| `/api/file/delete` | POST | 删除文件（需白名单） |
| `/api/file/chmod` | POST | 修改权限 |
| `/api/file/upload` | POST | 上传文件 |
| `/api/file/download` | GET | 单文件下载 |
| `/api/file/download/batch` | POST | 批量下载 |

### 配置管理
| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/whitelist` | GET/POST/DELETE/PUT | 白名单管理 |
| `/api/quickpaths` | GET/POST | 快捷路径管理 |
| `/api/userconfig` | GET/POST | 用户配置管理 |
| `/api/userconfig/reset` | POST | 重置用户配置 |
| `/api/userconfig/raw` | GET/POST | 原始配置读写 |
| `/api/changepwd` | POST | 修改密码 |

### 系统监控
| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/system` | GET | 系统监控信息 |

### AI / OCR
| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/ai/config` | GET | 获取AI配置 |
| `/api/ai/models` | GET | 获取可用模型列表 |
| `/api/ai/ocr` | POST | OCR文字识别 |

## 常见问题

**Q: 登录后显示 401 错误？**

A: 检查密码文件 `/etc/file-viewer/passwd` 是否存在，重新设置密码。

**Q: 无法编辑/上传文件？**

A: 检查配置文件中的 `folder_permissions` 和 `default_permissions` 设置。

**Q: 删除按钮不显示？**

A: 该路径不在删除白名单中，请在"设置"页面添加允许删除的路径。

**Q: 修改代码后不生效？**

A: 重启服务：`file-viewer restart`

**Q: 如何查看日志？**

```bash
file-viewer logs
# 或
journalctl -u file-viewer -f
```

**Q: OCR 识别失败？**

A: 检查 API Key 是否配置正确，可在工具页面配置 SiliconFlow API Key。

## 更新项目

```bash
cd /home/file-viewer
git pull
sudo file-viewer restart
```

## License

MIT License
