# memorygraph

[![GA](https://img.shields.io/badge/status-GA-brightgreen)]()
[![Version](https://img.shields.io/badge/version-0.0.1-blue)]()
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)]()
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey)]()
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen)]()
[![Ruff](https://img.shields.io/badge/lint-ruff-0-brightgreen)]()
[![Mypy](https://img.shields.io/badge/typecheck-mypy-0-brightgreen)]()
[![Bandit](https://img.shields.io/badge/security-bandit-0%20High%2FCritical-brightgreen)]()

一个带有语义增量层的本地代码知识图谱工具 —— 在编码过程中实现"使用、学习、沉淀"。

**100% 本地运行，无需任何外部 API 密钥。**

> **v0.0.1** | 覆盖率: 99.9% | 测试: 1304 | 语言: 7 | CLI 命令: 12 | MCP 工具: 20 | 语义搜索: ✅ | 性能: 2200+ 文件/秒

## 概述

memorygraph 使用 [tree-sitter](https://tree-sitter.github.io/) AST 解析来构建源代码的静态知识图谱，然后在其之上叠加人工策展的语义注解。结果是一个可查询、始终最新、越用越丰富的代码智能数据库。

### 双层架构

| 层 | 引擎 | 用途 |
|-------|--------|---------|
| **静态图** | tree-sitter + SQLite（或 PostgreSQL） | 从 AST 中确定性提取符号/边 |
| **语义层** | JSON 文档 | 人工策展的注解、设计意图、已知陷阱 |

静态层是骨干 —— 它不会因语义而改变。语义层是只增的辅助数据，它丰富查询而不损害确定性。

## 性能

| 指标 | 值 |
|--------|-------|
| 索引速度 | **>=150 文件/秒**（已验证 1000 个 Python 文件） |
| 查询延迟（P50） | < 1ms |
| 查询延迟（P99） | < 3ms |
| 测试覆盖率 | 100% |
| 索引内存 | ~200 MB / 1000 文件 |

**已验证项目：** black（337 文件）、flask（83 文件）、1000 文件合成压力测试。

通过 `ProcessPoolExecutor` 实现多核并行解析，并配合批量数据库事务（比逐文件提交快 2 倍以上）。

## 语言支持

| 特性 | Python | TypeScript | JavaScript | Go | Rust | Java | C# |
|---------|--------|------------|------------|----|------|------|-----|
| 符号提取 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 调用图 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 全文搜索 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 语义分析 | ✅ | --- | --- | --- | --- | --- | --- |
| 向量嵌入 | ✅ | --- | --- | --- | --- | --- | --- |

内置 7 种语言，零配置。

通过[插件系统](#plugin-system)可扩展 —— 添加自定义语言和分析器。

## 安装

### Docker（推荐）

```bash
docker pull zhangyiwen5512/memorygraph:latest
docker run -d --restart unless-stopped \
  -p 8765:8765 \
  -v $(pwd):/project \
  -v $(pwd)/.memorygraph:/home/memorygraph/.memorygraph \
  zhangyiwen5512/memorygraph
```

docker-compose 及高级选项参见[部署指南](docs/zh/DEPLOYMENT.md)。

### pip / 源码

```bash
git clone https://github.com/zhangyiwen5512/memorygraph.git
cd memorygraph
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

### 依赖要求

- Python 3.10+
- 平台特定的 tree-sitter 运行时（通过 pip 自动安装）
- 可选：用于复杂度分析的 `radon>=6.0`

## 快速开始

```bash
# 在项目目录中初始化
memorygraph init

# 全量索引
memorygraph index

# 检查状态
memorygraph status

# 搜索符号
memorygraph query "authentication"

# 查找任务上下文
memorygraph context "add user login"

# 显示受影响的符号
memorygraph affected src/auth.py

# 检测设计模式
memorygraph patterns

# 显示函数的 git 历史
memorygraph git-history "login"

# 列出已安装的插件
memorygraph plugins list

# 从 Claude Code 对话中提取注解
memorygraph extract-from-conversation --input conversation.json
```

## CLI 命令

### 项目管理

| 命令 | 描述 |
|---------|-------------|
| `memorygraph init` | 初始化 `.memorygraph/` 目录和数据库 |
| `memorygraph uninit` | 删除 `.memorygraph/` 及所有已索引数据，清理 MCP 配置 |
| `memorygraph install` | 在 `~/.claude.json` 中注册 MCP 服务器 |

### 索引

| 命令 | 描述 |
|---------|-------------|
| `memorygraph index` | 全量重新索引所有源文件，支持多核并行解析 |
| `memorygraph sync` | 增量同步 —— 仅重新解析变更的文件（基于 SHA256 哈希检查） |
| `memorygraph watch` | 启动文件监听器 —— 文件保存时自动同步 |

### 查询与分析

| 命令 | 描述 |
|---------|-------------|
| `memorygraph status` | 显示统计信息：文件、符号、边、语义覆盖率 |
| `memorygraph query <text>` | 符号全文搜索（FTS5） |
| `memorygraph files` | 列出所有已索引文件及其元数据 |
| `memorygraph context <task>` | 查找与任务相关的符号和入口点 |
| `memorygraph affected <file...>` | 显示文件变更所影响的符号（支持 `--from-diff`） |
| `memorygraph export` | 导出图为 Cytoscape.js JSON 格式 |
| `memorygraph patterns` | 检测设计模式（Singleton、Factory、Observer、Strategy、Decorator、Repository） |
| `memorygraph git-history <symbol>` | 通过 git 历史追踪符号级变更（`git log -L`） |

### 语义

| 命令 | 描述 |
|---------|-------------|
| `memorygraph semantic-ingest` | 导入文件的语义注解 |
| `memorygraph analyze` | 运行复杂度分析（需要 radon） |
| `memorygraph smells` | 列出检测到的代码异味 |
| `memorygraph metrics` | 显示复杂度指标 |
| `memorygraph extract-from-conversation` | 从 Claude Code JSON 导出文件中提取注解（启发式，无需 LLM） |

### 服务与插件

| 命令 | 描述 |
|---------|-------------|
| `memorygraph serve --mcp` | 启动 MCP stdio 服务器 |
| `memorygraph serve --web` | 启动 Web UI（交互式 Cytoscape.js 力导向图） |
| `memorygraph plugins list` | 列出内置和第三方插件 |

### 选项

大多数命令接受 `--project-root <path>`（默认：当前目录）：

```bash
memorygraph status --project-root /path/to/project
memorygraph index --project-root /path/to/project
```

### 自动排除

始终排除：`node_modules`、`vendor`、`dist`、`build`、`target`、`.venv`、`.next`、`__pycache__`、`.memorygraph`、`.git`、`.idea`、`.vscode`

`.gitignore` 中的模式也会被遵守。

## MCP（模型上下文协议）工具

memorygraph 通过 `memorygraph serve --mcp` 暴露 11 个 MCP 工具：

### 静态图工具

| 工具 | 描述 |
|------|-------------|
| `memorygraph_context` | 给定任务描述，返回入口点及相关符号及其调用者/被调用者。当语义数据可用时会**自动附加**。 |
| `memorygraph_search` | 按名称搜索符号及其位置。 |
| `memorygraph_callers` | 列出符号的调用者。支持 `file_path` 以消除同名符号歧义。 |
| `memorygraph_callees` | 列出符号的被调用者。支持 `file_path` 以消除同名符号歧义。 |
| `memorygraph_impact` | 分析修改符号的下游影响。 |
| `memorygraph_node` | 获取符号详情。支持 `file_path` 以消除跨文件同名符号歧义。 |
| `memorygraph_diff` | 解析 git diff，返回受影响的符号及其调用链。 |

### 语义工具

| 工具 | 描述 |
|------|-------------|
| `memorygraph_semantic_context` | 获取文件或符号的语义注解、洞见和未知问题。 |
| `memorygraph_annotations` | 获取人工编写的注解，可按文件或符号过滤。 |
| `memorygraph_unknowns` | 获取未解决的开放问题，按引用频率排序。 |
| `memorygraph_insights` | 获取跨已记录模块的设计洞见。 |

### 工具输入/输出示例

#### `memorygraph_context`

输入：
```json
{
  "task": "implement user authentication",
  "limit": 10
}
```

输出：
```json
{
  "task": "implement user authentication",
  "entry_points": [
    {
      "symbol": "AuthManager.login",
      "kind": "method",
      "file": "src/auth/manager.py",
      "signature": "def login(self, username: str, password: str) -> User",
      "relevance": 1.5
    }
  ],
  "related": [
    {
      "symbol": "AuthManager.login",
      "kind": "method",
      "file": "src/auth/manager.py",
      "callers": ["RequestHandler.authenticate"],
      "callees": ["UserStore.find_by_credentials"]
    }
  ],
  "semantic_context": [...]
}
```

#### `memorygraph_diff`

输入：
```json
{
  "diff": "diff --git a/src/auth.py b/src/auth.py\n--- a/src/auth.py\n+++ b/src/auth.py\n..."
}
```

输出：
```json
{
  "changed_files": ["src/auth.py"],
  "affected_symbols": ["login", "verify_password", "AuthManager"],
  "call_chains": {
    "login": ["RequestHandler.authenticate", "SessionManager.create"]
  }
}
```

## 设计模式检测

静态启发式检测 6 种常见模式 —— 无外部依赖：

| 模式 | 检测信号 |
|---------|-----------------|
| **Singleton（单例）** | `_instance` 属性或 `get_instance()` 方法 |
| **Factory（工厂）** | 名称包含 Factory/Builder，或返回同类型对象 |
| **Observer（观察者）** | `subscribe`/`on_`/`add_listener` + `notify`/`emit`/`trigger` 方法 |
| **Strategy（策略）** | 抽象基类 + 2 个及以上的具体实现 |
| **Decorator（装饰器）** | 名称包含 Decorator/Wrapper，或 `__init__` 接受被包装对象参数 |
| **Repository（仓库）** | 名称包含 Repository/Store/DAO，且具有 CRUD 方法 |

检测偏向保守 —— 宁可误报也不遗漏真实模式。
使用 `memorygraph patterns` 扫描你的项目。

## 插件系统

第三方语言和分析器通过 `pyproject.toml` 注册：

```toml
[project.entry-points."memorygraph.plugins"]
kotlin = "memorygraph_kotlin:KotlinPlugin"
```

两种插件类型：
- **LanguagePlugin**：为一种语言提供 AST 提取
- **AnalyzerPlugin**：提供附加分析（代码异味、指标、模式）

列出已安装的插件：`memorygraph plugins list`

## 语义层

语义层将人工策展的理解以 JSON 文档形式存储在 `.memorygraph/semantic/<文件路径哈希>.json`。文档是**只增**的 —— 合并操作永远不会删除已有的注解。使用 `filelock` 保证并发写入安全。

### 语义文档 Schema

```json
{
  "file": "src/auth/manager.py",
  "file_hash": "abc123...",
  "ingested_at": "2024-01-01T00:00:00Z",
  "source": "manual",
  "module_summary": "Authentication manager with pluggable backends",
  "annotations": [
    {
      "symbol": "login",
      "kind": "method",
      "summary": "Validates credentials and returns a User session",
      "design_intent": "Uses bcrypt for password hashing, supports MFA plugins",
      "pitfalls": "Watch for timing attacks on the MFA path"
    }
  ],
  "unknowns": [
    {
      "symbol": "rotate_key",
      "question": "When is key rotation triggered?",
      "context": "Referenced in session cleanup but purpose unclear"
    }
  ],
  "insights": [
    {
      "insight": "Auth module uses strategy pattern for backends",
      "related_symbols": ["AuthBackend", "LDAPBackend", "OAuthBackend"]
    }
  ]
}
```

### 添加语义数据

```bash
# 手动导入
memorygraph semantic-ingest --file src/auth.py --summary "Authentication module"

# 从 Claude Code 对话中提取
memorygraph extract-from-conversation --input conversation.json

# 通过 PostToolUse 钩子自动导入（添加到 .claude/settings.json）：
# {
#   "hooks": {
#     "PostToolUse": [{
#       "matcher": "Write|Edit",
#       "hooks": [{
#         "type": "command",
#         "command": "memorygraph semantic-ingest --file $CLAUDE_TOOL_FILE --source 'hook'"
#       }]
#     }]
#   }
# }
```

## 存储

所有数据本地存储在 `.memorygraph/` 目录下：

```
.memorygraph/
├── memorygraph.db          # SQLite（schema + FTS5 + 数据）
└── semantic/               # 语义 JSON 文档
    ├── <hash1>.json
    └── <hash2>.json
```

### PostgreSQL 支持（实验性）

设置 `DATABASE_URL` 环境变量以使用 PostgreSQL 替代 SQLite：

```bash
export DATABASE_URL="postgresql://user:pass@localhost/memorygraph"
memorygraph init
memorygraph index
```

使用抽象的 `AbstractRepository`，后端实现包括 `SQLiteRepository`（默认）和 `PostgreSQLRepository`。全文搜索通过 PostgreSQL `tsvector` + GIN 索引实现。

### 数据库 Schema

- `files` —— 文件元数据，含 SHA256 哈希（用于增量同步）
- `functions`、`methods`、`classes`、`interfaces`、`type_aliases`、`variables` —— 符号表
- `edges` —— 调用关系，包含复合索引 `(target, kind)` + `(source, kind)` 以支持快速图遍历
- `fts_index` —— FTS5 虚拟表，带批量插入优化

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行全部测试（763 个测试，99% 覆盖率）
pytest

# 运行特定测试文件
pytest tests/test_semantic.py -v

# 覆盖率报告
python -m coverage run --source=src/memorygraph -m pytest && python -m coverage report
```

## 已知限制

- Web 服务器为单线程（`http.server`）
- 导出上限为 500 节点（浏览器内存限制）
- 模式检测为启发式（偏向保守；存在一些误报）
- PostgreSQL 后端需要 `psycopg2`（不会自动安装）
- `memorygraph watch` 为桩实现 —— 请使用 `memorygraph sync` 进行手动增量更新
- 设计模式检测可能产生误报（有意为之 —— 优先召回率而非精确率）

## 许可证

MIT
