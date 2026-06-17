# memorygraph 部署指南

## 环境要求

| 组件 | 最低版本 | 推荐版本 |
|------|---------|---------|
| Python | 3.10 | 3.11+ |
| pip | 22.0+ | 最新版 |
| tree-sitter | 0.21+ | 0.22+ |
| SQLite | 3.35+ | 3.40+ |
| 磁盘空间 | 200 MB | 1 GB+ |
| 内存 | 512 MB | 2 GB+ |

可选依赖（语义功能需要）：

| 组件 | 用途 | 说明 |
|------|------|------|
| sentence-transformers | 代码嵌入向量 | 需下载 all-MiniLM-L6-v2 模型（~90MB） |
| PostgreSQL 14+ | 生产级后端 | 替代默认 SQLite |
| PyTorch 2.0+ | GPU 加速嵌入 | CPU 也可运行，速度较慢 |

### SQLite vs PostgreSQL

memorygraph **默认使用 SQLite** — 零配置，单文件，单用户场景完全够用。PostgreSQL 是可选的，仅在团队共享图谱时才有价值。

**SQLite 足够的情况：**
- 你是唯一的用户
- 不想做任何额外配置
- 不需要并发写入

**PostgreSQL 仅在以下场景需要：**
- 多人共享同一个图谱
- 你已有 PG 实例，希望统一管理

#### 连接已有的 PostgreSQL（Docker）

如果宿主机上已运行 PG，想让 Docker 容器内的 memorygraph 连接它：

```bash
docker run \
  --add-host host.docker.internal:host-gateway \
  -e PGHOST=host.docker.internal \
  -e PGPORT=5432 \
  -e PGUSER=你的用户名 \
  -e PGPASSWORD=你的密码 \
  -e PGDATABASE=你的库名 \
  -p 8765:8765 -v $(pwd):/project \
  zhangyiwen5512/memorygraph
```

> 容器内的 `localhost` 指向容器自身，不是你的电脑。`host.docker.internal` 才是从容器访问宿主机的地址。

## 安装方式

### 方式 1：从 PyPI 安装（推荐）

```bash
pip install memorygraph
```

带语义功能：

```bash
pip install memorygraph[semantic]
```

带 PostgreSQL 支持：

```bash
pip install memorygraph[postgres]
```

全功能安装：

```bash
pip install memorygraph[all]
```

### 方式 2：从源码安装

```bash
git clone https://github.com/user/memorygraph.git
cd memorygraph
pip install -e .
```

开发模式（包含测试依赖）：

```bash
pip install -e ".[dev,test]"
```

### 方式 3：Docker

预构建镜像已发布到 Docker Hub：[`zhangyiwen5512/memorygraph`](https://hub.docker.com/r/zhangyiwen5512/memorygraph)

```bash
# 拉取镜像
docker pull zhangyiwen5512/memorygraph:latest

# 快速启动 — 守护进程 + Web UI（数据持久化到 ./.memorygraph/）
docker run -d --restart unless-stopped \
  -p 8765:8765 \
  -v $(pwd):/project \
  -v $(pwd)/.memorygraph:/home/memorygraph/.memorygraph \
  zhangyiwen5512/memorygraph

# 初始化新项目
docker run -v $(pwd):/project zhangyiwen5512/memorygraph init

# 索引项目
docker run -v $(pwd):/project zhangyiwen5512/memorygraph index

# 查询
docker run -v $(pwd):/project zhangyiwen5512/memorygraph query "authentication"

# 启动 MCP 服务（stdio 模式）
docker run -i -v $(pwd):/project zhangyiwen5512/memorygraph serve --mcp
```

#### 镜像标签

| 标签 | 说明 |
|------|------|
| `latest` | 最新稳定版（推荐） |
| `0.0.1` | 指定版本锁定 |

#### 挂载目录

| 路径 | 用途 |
|------|------|
| `/project` | 你的代码库（必需） |
| `/home/memorygraph/.memorygraph` | 索引数据持久化（推荐） |

#### docker-compose（SQLite — 默认）

```bash
# 启动 serve + Web UI
docker-compose up -d

# 启动 serve + 文件监控（变更时自动重建索引）
docker-compose --profile watch up -d
```

#### docker-compose（PostgreSQL — 生产环境）

```bash
# 启动 PostgreSQL 后端
docker-compose --profile postgres up -d

# 使用 PG 后端初始化
docker-compose --profile postgres run --rm memorygraph init --backend postgres --dsn "postgresql://memorygraph:memorygraph@postgres/memorygraph"

# 同时启动 PG 和文件监控
docker-compose --profile postgres --profile watch up -d
```

完整的服务定义见仓库中的 `docker-compose.yml`。

#### 从源码构建

```bash
git clone https://github.com/zhangyiwen5512/memorygraph.git
cd memorygraph
docker build -t memorygraph .
docker run -p 8765:8765 -v $(pwd):/project memorygraph
```

## 模型下载

memorygraph 的语义搜索功能依赖 `all-MiniLM-L6-v2` 模型（~90 MB）。

### 自动下载

首次运行语义功能时自动下载：

```bash
memorygraph serve           # 启动时检查模型
memorygraph semantic stats  # 触发下载
```

### 手动下载（离线/网络受限环境）

**步骤 1**：在有网络的机器上下载模型：

```bash
pip install huggingface-hub
hf download sentence-transformers/all-MiniLM-L6-v2 \
  --local-dir ./all-MiniLM-L6-v2 \
  --local-dir-use-symlinks False
```

**步骤 2**：将模型目录复制到目标机器，放置到以下任一位置：

```bash
# 用户级（推荐）
~/.cache/sentence-transformers/all-MiniLM-L6-v2/

# 项目级（与仓库一起管理）
.memorygraph/models/all-MiniLM-L6-v2/

# 系统级
/usr/local/share/sentence-transformers/all-MiniLM-L6-v2/
```

**步骤 3**：验证模型可用：

```bash
memorygraph doctor  # 检查模型状态
```

### HuggingFace 镜像

如果 HuggingFace 官方站点不可达（中国大陆等），使用镜像：

```bash
export HF_ENDPOINT=https://hf-mirror.com
memorygraph semantic stats  # 通过镜像下载
```

### SOCKS 代理兼容性

如果系统设置了 `ALL_PROXY=socks://...`，Python 的 `huggingface_hub` 和 `sentence-transformers` 库无法使用 SOCKS 代理。

**解决方案（已验证）：**

```bash
# 1. 取消 SOCKS 代理（使用 HTTP 代理或不使用代理）
unset ALL_PROXY SOCKS_PROXY all_proxy socks_proxy

# 2. 使用 HuggingFace 镜像（推荐）
export HF_ENDPOINT=https://hf-mirror.com

# 3. 使用 hf CLI 下载模型（会自动使用 HTTP 代理或直连）
hf download sentence-transformers/all-MiniLM-L6-v2

# 4. 验证
python3 -c "from sentence_transformers import SentenceTransformer;   m = SentenceTransformer('all-MiniLM-L6-v2', local_files_only=True);   print('OK:', m.get_embedding_dimension(), 'dims')"
```

> **注意**：`hf` CLI（新版 `huggingface-cli`）使用不同的网络栈，比 Python SDK 更容易通过代理。

### SOCKS 代理问题详解

SOCKS 代理在 Python 的网络栈中支持有限，原因如下：

1. **标准库限制**：Python 内置的 `urllib` / `requests` 库仅支持 HTTP/HTTPS 代理，不支持 SOCKS 协议。
2. **第三方依赖**：`huggingface_hub` 和 `sentence-transformers` 底层使用 `requests`，若要使用 SOCKS 代理，需额外安装 `pysocks` 或 `PySocks`，且依赖版本可能不兼容。
3. **常见症状**：
   - 模型下载卡住不动，最终超时报错
   - 出现 `ConnectionError` 或 `RemoteDisconnected` 异常
   - `huggingface_hub` 返回 `401 Unauthorized` 或连接失败

**推荐方案（按优先级排序）：**

| 优先级 | 方案 | 说明 |
|--------|------|------|
| 1 | 取消 SOCKS 代理，改用直连 | 最可靠，适用于有直连能力的环境 |
| 2 | 设置 `HF_ENDPOINT` 为镜像站点 | 国内用户首选，绕开国际网络瓶颈 |
| 3 | 使用 `hf ` CLI 命令行工具下载 | CLI 使用不同的网络栈，对代理兼容性更好 |
| 4 | 安装 `pysocks` 并配置 HTTP 代理 | 针对必须通过代理的环境：`pip install pysocks` 后设置 `http_proxy` 和 `https_proxy` |
| 5 | 手动下载模型并离线导入 | 完全绕开网络，适用于完全隔离的内网环境 |

> **提醒**：如果上述方案仍无法解决，建议联系网络管理员确认代理配置或开通 HuggingFace 直接访问权限。

## 快速开始

```bash
# 1. 初始化项目
memorygraph init ./my-project

# 2. 索引代码
cd my-project
memorygraph index

# 3. 查询
memorygraph query "authentication"
memorygraph find MyClass

# 4. 启动 MCP 服务
memorygraph serve --mcp
```

## 配置

配置文件：`.memorygraph/config.json`（项目级）或 `~/.config/memorygraph/config.json`（用户级）

```json
{
  "storage": {
    "backend": "sqlite",
    "database": ".memorygraph/memorygraph.db"
  },
  "parsing": {
    "max_file_size_mb": 10,
    "exclude_patterns": ["node_modules/", ".git/", "__pycache__/"]
  },
  "semantic": {
    "model_name": "all-MiniLM-L6-v2",
    "batch_size": 32
  },
  "server": {
    "host": "127.0.0.1",
    "port": 8765
  }
}
```

## PostgreSQL 配置

```bash
# 安装 PostgreSQL 支持
pip install memorygraph[postgres]

# 创建数据库
createdb memorygraph

# 初始化
memorygraph init --backend postgres --dsn "postgresql://user:pass@localhost/memorygraph"
```

## 开发环境

```bash
# 克隆仓库
git clone https://github.com/user/memorygraph.git
cd memorygraph

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate

# 安装开发依赖
pip install -e ".[dev,test,all]"

# 运行测试
pytest

# 代码质量检查
ruff check src/
mypy src/
vulture src/ --min-confidence 80
```

## 生产部署

### 使用 waitress（Windows/Linux）

```bash
pip install waitress
waitress-serve --host 0.0.0.0 --port 8765 memorygraph.web.app:app
```

### 使用 gunicorn（Linux/macOS）

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:8765 memorygraph.web.app:app
```

### systemd 服务

```ini
# /etc/systemd/system/memorygraph.service
[Unit]
Description=memorygraph MCP Server
After=network.target

[Service]
Type=simple
User=memorygraph
WorkingDirectory=/opt/memorygraph
ExecStart=/opt/memorygraph/.venv/bin/memorygraph serve --host 0.0.0.0 --port 8765
Restart=always
RestartSec=10
Environment=HF_ENDPOINT=https://hf-mirror.com

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now memorygraph
```

## 故障排查

### 模型下载失败

```bash
# 检查网络
curl -I https://huggingface.co

# 使用镜像
export HF_ENDPOINT=https://hf-mirror.com

# 手动下载（见上文）
```

### tree-sitter 编译错误

```bash
# 需要 C 编译器
sudo apt install build-essential  # Debian/Ubuntu
brew install gcc                   # macOS

pip install --no-binary tree-sitter tree-sitter
```

### SQLite 版本过低

```bash
# 检查版本
python3 -c "import sqlite3; print(sqlite3.sqlite_version)"

# 升级（需要 3.35+）
pip install pysqlite3-binary
```

### 权限问题

```bash
# Linux: 确保用户对项目目录有写权限
chown -R $USER:$USER /path/to/project

# macOS: 检查隐私与安全设置
```
