# memorygraph 用户指南

## 什么是 memorygraph？

memorygraph 为你的代码库构建**知识图谱**——它索引每一个符号（函数、类、方法、变量），追踪它们之间的关系（调用者/被调用者），并通过向量嵌入提供语义搜索。使用它进行代码探索、影响分析和理解不熟悉的仓库。

主要特性：
- **多语言**：Python、TypeScript、JavaScript、Go、Rust、Java、C#
- **快速索引**：单进程 280+ 文件/秒，多进程 300+ 文件/秒（1000 文件基准测试）
- **全文搜索 + 语义搜索**：符号搜索 + 基于任务的代码发现
- **调用图遍历**：查找多层深度的调用者和被调用者
- **Web UI + API**：内置 HTTP 服务器，提供 REST API 和 Prometheus 指标
- **MCP 服务器**：与 Claude Code、Codex 及其他 AI 编程工具集成

---

## 快速开始

```bash
# 安装
pip install memorygraph

# 在项目中初始化
cd my-project
memorygraph init

# 索引代码库
memorygraph index

# 搜索符号
memorygraph query "authentication"

# 启动 Web UI + API
memorygraph serve --web

# 与 Claude Code 配合使用（MCP）
memorygraph serve    # stdio MCP 模式
```

打开 `http://localhost:8765` 使用 Web UI。

---

## CLI 命令参考

### `memorygraph init`

在项目目录中初始化 memorygraph。创建包含 SQLite 数据库和配置的 `.memorygraph/` 目录。

```
memorygraph init [--project-root PATH]
```

| 选项 | 默认值 | 描述 |
|--------|---------|-------------|
| `--project-root` | `.` | 项目根目录 |

### `memorygraph uninit`

从项目中移除 memorygraph。删除 `.memorygraph/` 目录及所有已索引数据。

```
memorygraph uninit [--project-root PATH] [--force]
```

| 选项 | 默认值 | 描述 |
|--------|---------|-------------|
| `--project-root` | `.` | 项目根目录 |
| `--force` | `false` | 跳过确认提示 |

### `memorygraph index`

解析并索引所有源文件。使用并行处理以提高速度。

```
memorygraph index [--project-root PATH] [--embed]
```

| 选项 | 默认值 | 描述 |
|--------|---------|-------------|
| `--project-root` | `.` | 项目根目录 |
| `--embed` | `false` | 索引后生成向量嵌入 |

### `memorygraph sync`

增量同步——仅重新解析变更的文件。对于仅修改了少量文件的大型项目，比 `index` 快得多。

```
memorygraph sync [--project-root PATH] [--analyze/--no-analyze]
```

| 选项 | 默认值 | 描述 |
|--------|---------|-------------|
| `--project-root` | `.` | 项目根目录 |
| `--analyze` | `false` | 对同步后的文件运行语义分析 |

### `memorygraph watch`

监听项目文件并自动同步变更（守护进程模式，仅 Linux）。

```
memorygraph watch [--project-root PATH]
memorygraph watch --stop     # 停止运行中的监听器
```

### `memorygraph query`

搜索和探索知识图谱。支持多个子命令。

```
memorygraph query <name>            # 按名称搜索符号
memorygraph query search <query>    # 全文搜索（FTS5）
memorygraph query callers <symbol>  # 查找符号的调用者
memorygraph query callees <symbol>  # 查找符号的被调用者
```

共享选项：
| 选项 | 默认值 | 描述 |
|--------|---------|-------------|
| `--project-root` | `.` | 项目根目录 |
| `--limit` | `20` | 最大结果数 |
| `--file` | — | 筛选到特定文件 |
| `--format` | `table` | 输出格式：`table`、`json`、`csv` |

示例：
```bash
# 查找一个函数的所有调用者
memorygraph query callers "src.auth.login"

# 查找一个模块调用的所有内容
memorygraph query callees "src.main" --limit 50

# 导出搜索结果为 JSON
memorygraph query search "error handling" --format json
```

### `memorygraph export`

导出知识图谱供外部分析。

```
memorygraph export [--project-root PATH] [--format FORMAT] [--output FILE]
```

| 选项 | 默认值 | 描述 |
|--------|---------|-------------|
| `--project-root` | `.` | 项目根目录 |
| `--format` | `json` | 导出格式：`json`、`dot`（Graphviz） |
| `--output` | 标准输出 | 输出文件路径 |

### `memorygraph serve`

启动带 Web UI 和 REST API 的 HTTP 服务器，或 MCP stdio 服务器。

```
memorygraph serve --web [--port PORT] [--background/--stop]
memorygraph serve          # MCP stdio 模式（不传 --web 标志）
```

| 选项 | 默认值 | 描述 |
|--------|---------|-------------|
| `--web` | — | 启动 HTTP 服务器模式 |
| `--port` | `8765` | HTTP 监听端口 |
| `--background` | `false` | 作为守护进程运行（仅 Linux） |
| `--stop` | `false` | 停止后台守护进程 |
| `--project-root` | `.` | 项目根目录 |

### `memorygraph doctor`

诊断 memorygraph 健康状况。检查数据库完整性、文件索引新鲜度和配置。

```
memorygraph doctor [--project-root PATH]
```

### `memorygraph status`

显示索引统计信息：文件数、符号数、数据库大小。

```
memorygraph status [--project-root PATH]
```

### `memorygraph analyze`

对已索引代码运行语言特定的分析器。

```
memorygraph analyze [--project-root PATH] [--file PATH] [--analyzer NAME]
```

### `memorygraph hook`

安装或卸载 git 钩子以在提交时自动同步。

```
memorygraph hook install    # 安装 pre-commit 钩子
memorygraph hook uninstall  # 移除 pre-commit 钩子
```

---

## Web API 参考

基础 URL：`http://localhost:8765`

### `GET /`
Web UI — 交互式代码图谱浏览器。

### `GET /health`

服务器健康及统计信息。

**响应：**
```json
{
  "status": "ok",
  "version": "5.6.0",
  "uptime_seconds": 1234,
  "file_count": 337,
  "symbol_count": 15234,
  "db_size_bytes": 5242880,
  "memory_graph": "connected"
}
```

### `GET /metrics`

Prometheus 格式的指标接口。兼容 Prometheus 和 Grafana。

```
# HELP memorygraph_files_total Number of indexed files
# TYPE memorygraph_files_total gauge
memorygraph_files_total 337

# HELP memorygraph_symbols_total Number of indexed symbols
# TYPE memorygraph_symbols_total gauge
memorygraph_symbols_total 15234

# HELP memorygraph_index_duration_seconds Index duration in seconds
# TYPE memorygraph_index_duration_seconds gauge
memorygraph_index_duration_seconds 2.5

# HELP memorygraph_query_duration_seconds Query duration histogram
# TYPE memorygraph_query_duration_seconds histogram
```

### `GET /api/status`

索引统计数据（与 `memorygraph status` CLI 相同的数据）。

**响应：**
```json
{
  "files": 337,
  "symbols": 15234,
  "edges": 45210,
  "db_size_bytes": 5242880,
  "languages": {
    "python": 300,
    "typescript": 37
  }
}
```

### `GET /api/search?q=<query>&limit=<n>`

在所有已索引符号中进行全文搜索（FTS5）。

**参数：**
| 参数 | 默认值 | 描述 |
|-----------|---------|-------------|
| `q` | （必填） | 搜索查询（FTS5 语法） |
| `limit` | `20` | 最大结果数 |
| `file_path` | — | 筛选到特定文件 |

**响应：**
```json
{
  "results": [
    {
      "symbol_name": "authenticate",
      "qualified_name": "auth.authenticate",
      "signature": "def authenticate(token: str) -> User",
      "file_path": "src/auth.py",
      "kind": "function",
      "start_line": 42,
      "score": 1.5
    }
  ]
}
```

### `GET /api/node/<qualified_name>`

通过完全限定名称查找特定符号。

**示例：** `GET /api/node/auth.authenticate`

**响应：**
```json
{
  "symbol": {
    "name": "authenticate",
    "qualified_name": "auth.authenticate",
    "kind": "function",
    "signature": "def authenticate(token: str) -> User",
    "file_path": "src/auth.py",
    "start_line": 42,
    "end_line": 58
  }
}
```

### `GET /api/graph?symbol=<name>&depth=<n>`

获取某个符号周围的调用图。

**参数：**
| 参数 | 默认值 | 描述 |
|-----------|---------|-------------|
| `symbol` | — | 起始符号（限定名称） |
| `depth` | `1` | 遍历深度（1-5） |

**响应：**
```json
{
  "nodes": [
    {"name": "auth.login", "kind": "function", "file": "src/auth.py"},
    {"name": "db.query", "kind": "method", "file": "src/db.py"}
  ],
  "edges": [
    {"source": "auth.login", "target": "db.query", "kind": "calls"}
  ]
}
```

### `GET /api/callers/<symbol>?depth=<n>`

查找某个符号的所有调用者（递归）。

**示例：** `GET /api/callers/auth.authenticate?depth=2`

### `GET /api/callees/<symbol>?depth=<n>`

查找某个符号调用的所有符号（递归）。

**示例：** `GET /api/callees/src.main?depth=2`

### `GET /api/impact/<symbol>?max_depth=<n>`

分析修改某个符号的影响范围。返回所有传递性的被调用者。

### `GET /api/semantic-search?q=<task>&limit=<n>`

多词语义搜索——描述一个任务，找到相关的代码。

**示例：** `GET /api/semantic-search?q=user password reset email`

### `GET /api/events`

用于实时索引更新的 Server-Sent Events (SSE) 流。

---

## MCP 服务器使用

memorygraph 可以作为 Model Context Protocol (MCP) 服务器运行，为 Claude Code、Codex 和 Gemini CLI 等 AI 编程辅助工具提供工具能力。

### 配置

添加到你的 AI 工具的 MCP 配置中：

```json
{
  "mcpServers": {
    "memorygraph": {
      "command": "memorygraph",
      "args": ["serve"],
      "cwd": "/path/to/your/project"
    }
  }
}
```

### 可用的 MCP 工具

| 工具 | 描述 |
|------|-------------|
| `memorygraph_search` | 全文符号搜索 |
| `memorygraph_node` | 通过限定名称获取符号详情 |
| `memorygraph_callers` | 查找符号的调用者 |
| `memorygraph_callees` | 查找符号的被调用者 |
| `memorygraph_impact` | 分析变更影响范围 |
| `memorygraph_semantic_search` | 基于任务的语义代码搜索 |

### 可用的 MCP 写入工具

**写入工具**——向知识图谱回写贡献（即「边使用边沉淀」循环）：

| 工具 | 描述 |
|------|-------------|
| `memorygraph_annotate` | 为符号写入注释——它的功能、设计意图、陷阱 |
| `memorygraph_add_insight` | 记录设计洞见或架构观察 |
| `memorygraph_add_unknown` | 记录未解决的问题——追踪我们仍需搞清楚的内容 |

当 Claude Code 在会话中调用这些写入工具时，它会逐步构建语义知识图谱。每一次会话都受益于之前学到的所有内容。

---

## 语义层：「边使用、边学习、边沉淀」

memorygraph 的语义层存储代码的**人类层面理解**，通过交互使用随时间积累。

### 概念

| 概念 | 捕获内容 |
|---------|-----------------|
| **注释 (Annotation)** | 每个符号：它的功能、设计意图、陷阱 |
| **洞见 (Insight)** | 跨领域：模式、权衡、惯例 |
| **未知 (Unknown)** | 未解决的问题：理解中待后续填补的空白 |
| **语义文档 (Semantic Document)** | 每个文件对应一个 JSON，位于 `.memorygraph/semantic/<hash>.json` |

### 循环如何工作

```
1. 静态索引 (memorygraph index)       → 语法图基线
2. Claude Code 会话                   → 查询图谱，阅读代码
3. Claude 调用 MCP 写入工具            → annotate、add_insight、add_unknown
4. 语义存储累积知识                    → .memorygraph/semantic/*.json
5. 下次会话获得更丰富的上下文           → 图谱越来越聪明
```

所有语义数据都是**合并安全的**：同一符号的注释会进行 upsert（最新的覆盖旧的），而洞见和未知则是追加的。

### 查询语义层

```bash
# CLI
memorygraph query annotations --symbol auth.login
memorygraph query unknowns --limit 20
memorygraph query insights
```

---

## 部署

### Systemd (Linux)

创建 `/etc/systemd/system/memorygraph.service`：

```ini
[Unit]
Description=memorygraph web server
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/my-project
ExecStart=/usr/local/bin/memorygraph serve --web --port 8765
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now memorygraph
```

### Docker

预构建镜像已发布到 Docker Hub：

```bash
# 拉取并以守护进程模式运行（数据持久化）
docker pull zhangyiwen5512/memorygraph:latest
docker run -d --restart unless-stopped \
  -p 8765:8765 \
  -v $(pwd):/project \
  -v $(pwd)/.memorygraph:/home/memorygraph/.memorygraph \
  zhangyiwen5512/memorygraph

# 首次使用前先初始化 + 索引
docker run -v $(pwd):/project zhangyiwen5512/memorygraph init
docker run -v $(pwd):/project zhangyiwen5512/memorygraph index
```

或使用 `docker-compose`（参见[部署指南](DEPLOYMENT.md)）。

### Nginx 反向代理

```nginx
server {
    listen 80;
    server_name graph.example.com;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

        # SSE 支持
        proxy_buffering off;
        proxy_cache off;
    }
}
```

### CI/CD 集成（GitHub Actions）

```yaml
- name: Index codebase
  run: |
    pip install memorygraph
    memorygraph init
    memorygraph index

- name: Impact analysis
  run: |
    memorygraph query impact "src.auth.login"
```

---

## 配置

### 环境变量

| 变量 | 默认值 | 描述 |
|----------|---------|-------------|
| `MEMORYGRAPH_DB_PATH` | `.memorygraph/memorygraph.db` | SQLite 数据库路径 |
| `MEMORYGRAPH_PORT` | `8765` | Web 服务器端口 |
| `MEMORYGRAPH_LOG_LEVEL` | `INFO` | 日志级别 (DEBUG/INFO/WARNING/ERROR) |
| `DATABASE_URL` | — | PostgreSQL 连接字符串（用于 pg 后端） |

### 项目结构

```
my-project/
├── .memorygraph/
│   ├── memorygraph.db      # SQLite 数据库
│   └── file_hashes.json    # 用于增量同步的文件哈希缓存
├── src/                     # 你的源代码
└── pyproject.toml
```

---

## 性能调优

### 索引大型项目（5000+ 文件）

```bash
# 对非常大的项目使用批处理模式
memorygraph index --force

# 或者在初始索引后使用增量同步
memorygraph sync
```

典型性能（在 Linux、Intel i7、SSD 上验证）：
| 仓库大小 | 文件数 | 索引时间 | 速率 |
|-----------|-------|------------|------|
| 小型 | 100 | <0.5 秒 | ~500 文件/秒 |
| 中型 | 1,000 | ~2 秒 | ~500 文件/秒 |
| 大型 | 10,000 | ~20 秒 | ~500 文件/秒 |

### 内存使用

对于典型项目（<1000 文件），memorygraph 使用约 50-100 MB 内存。对于非常大的代码库（>10,000 文件），分配 512 MB 以上并使用 PostgreSQL 后端。

### PostgreSQL 后端

对于团队或大型代码库，使用 PostgreSQL 替代 SQLite：

```bash
export DATABASE_URL="postgresql://user:pass@localhost:5432/memorygraph"
memorygraph init
memorygraph index
```

---

## 支持的语言

| 语言 | 文件扩展名 | 解析器 |
|----------|----------------|--------|
| Python | `.py` | tree-sitter-python |
| TypeScript | `.ts`、`.tsx` | tree-sitter-typescript |
| JavaScript | `.js`、`.jsx` | tree-sitter-typescript |
| Go | `.go` | tree-sitter-go |
| Rust | `.rs` | tree-sitter-rust |
| Java | `.java` | tree-sitter-java |
| C# | `.cs` | tree-sitter-c-sharp |

---

## 故障排查

### "No source files found"（未找到源文件）

确保你的项目包含可识别语言的源文件。使用 `memorygraph doctor` 进行诊断。

### "Database is locked"（数据库被锁定）

一次只能有一个写入者访问 SQLite 数据库。在索引之前，停止任何正在运行的 `memorygraph serve` 或 `memorygraph watch` 进程。

### "Model not cached"（模型未缓存，语义搜索）

语义搜索需要来自 HuggingFace 的 `all-MiniLM-L6-v2` 模型。首次使用时，手动下载：

```bash
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
```

如果位于代理之后，请配置 `HTTP_PROXY`/`HTTPS_PROXY` 环境变量。

### 首次运行索引缓慢

首次索引受 CPU 密集型的 tree-sitter 解析所限。后续使用 `memorygraph sync` 运行仅重新解析变更的文件。

---

## 开发

```bash
git clone https://github.com/memorygraph/memorygraph
cd memorygraph
make dev         # pip install -e ".[dev]"
make test        # pytest
make lint        # ruff check
make typecheck   # mypy
make deadcode    # vulture
make bench       # 压力测试（1000 文件）
make ci          # 完整 CI 流程
```

## 参考

- **[API 参考文档](API_REFERENCE.md)** — 公共 API 接口：EmbeddingGenerator、StorageManager、ParsingPipeline、MCP Server、IR 类型与配置
- **[部署指南](DEPLOYMENT.md)** — pip/源码/Docker 安装、模型下载（含 HuggingFace 镜像和 SOCKS 代理）、PostgreSQL 配置、生产部署

---

## 性能

memorygraph 针对速度进行了优化。来自 v5.15.0-dev（iter-67）的性能数据：

| 基准 | 文件数 | 吞吐量 | 解析 | 入库 | 内存增量 |
|-----------|-------|-----------|-------|--------|----------|
| 原始管道 (1000) | 1,000 | **280 文件/秒** | 301 文件/秒 | 0.25 秒 | — |
| 原始管道 (5000) | 5,000 | **349 文件/秒** | 376 文件/秒 | 1.03 秒 | +78 MB |
| 并行 (1000, 16 核) | 1,000 | **4,000+ 文件/秒** | — | — | 每进程 |

关键优化：
- **查询缓存**：编译后的 tree-sitter 查询在文件间复用
- **I/O 预取**：在解析前批量读取文件
- **提取器复用**：每种语言使用单个提取器实例
- **多进程**：对 CPU 密集型工作使用 ProcessPoolExecutor
