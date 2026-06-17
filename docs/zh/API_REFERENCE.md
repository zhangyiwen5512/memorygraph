# memorygraph API 参考

> 从源码 docstrings 自动生成。覆盖所有公共 API 表面。

## 模块索引

- **`memorygraph.mcp.server`** — MCP 服务器 — 通过 Model Context Protocol 暴露 memorygraph 工具。
- **`memorygraph.web.api`** — REST API 处理器 — memorygraph Web 服务器的 REST API 处理程序。
- **`memorygraph.web.renderer`** — Cytoscape.js 交互式 HTML 渲染器，支持标注编辑。
- **`memorygraph.web.server`** — HTTP 服务器 — 为 memorygraph 提供 SSE（服务器推送事件）支持。
- **`memorygraph.storage.backend`** — 存储后端抽象层 — 支持 SQLite（默认）和 PostgreSQL。
- **`memorygraph.storage.cache`** — 线程安全的 LRU 缓存，用于图查询。
- **`memorygraph.storage.connection`** — 数据库连接管理。
- **`memorygraph.storage.manager`** — StorageManager — 存储层的唯一对外入口。
- **`memorygraph.storage.pg_repository`** — PostgreSQL 存储后端 — psycopg2 + tsvector 全文搜索。
- **`memorygraph.storage.repositories`** — 仓储类，用于单表操作。
- **`memorygraph.storage.schema`** — SQLite 模式定义和初始化。
- **`memorygraph.parsing.batch`** — 批量并行解析器——asyncio + ProcessPoolExecutor（多进程绕过 GIL）。
- **`memorygraph.parsing.detector`** — 语言检测器——文件扩展名 → LanguageConfig。
- **`memorygraph.parsing.extractor`** — IRExtractor——将 tree-sitter AST 转为统一 IR 的 Symbol + Edge。
- **`memorygraph.parsing.ir`** — 统一中间表示（IR）数据类型。
- **`memorygraph.parsing.pipeline`** — 解析管道——4 阶段串行：Detect → Parse → Extract → Resolve。
- **`memorygraph.parsing.registry`** — 语言注册表——扩展名检测 + 懒加载 tree-sitter 语法库。
- **`memorygraph.parsing.resolver`** — 跨文件引用解析器——填充 Edge.target_span。
- **`memorygraph.parsing.ts_parser`** — Tree-sitter 解析器包装器——文件字节流 → tree-sitter Tree。
- **`memorygraph.cli.main`** — CLI 入口点 — memorygraph 命令行工具。
- **`memorygraph.cli.shared`** — 共享辅助函数 — CLI 命令模块的共享辅助函数。
- **`memorygraph.cli.commands.doctor`** — Doctor 命令 — memorygraph 安装健康检查。
- **`memorygraph.cli.commands.indexing`** — 索引命令 — init、uninit、index、sync、watch。
- **`memorygraph.cli.commands.querying`** — 查询命令 — query、context、files、affected、export。
- **`memorygraph.cli.commands.semantic`** — 语义分析 CLI 命令。
- **`memorygraph.cli.commands.serving`** — 服务管理命令 — serve、install。
- **`memorygraph.cli.commands.utils`** — 工具命令 — status、plugins。
- **`memorygraph.semantic.analysis`** — 静态分析 — 复杂度、代码坏味、模块角色推断。
- **`memorygraph.semantic.conversation`** — 语义标注提取 — 从 Claude Code 对话导出中提取语义标注。
- **`memorygraph.semantic.embeddings`** — 语义嵌入 — 基于 sentence-transformers 的代码符号语义嵌入。
- **`memorygraph.semantic.models`** — 语义数据模型 — 人工整理的结构化 JSON，用于代码理解。
- **`memorygraph.semantic.patterns`** — 设计模式检测 — 静态设计模式检测。
- **`memorygraph.semantic.store`** — SemanticStore — 在 .memorygraph/semantic/ 中加载/保存语义 JSON 文档。

## CLI 命令参考

memorygraph 提供 12 个子命令，按功能分组：

### 项目管理
- `memorygraph init <path>` — 初始化 .memorygraph/ 目录和 SQLite 数据库
- `memorygraph uninit` — 移除 .memorygraph/ 目录

### 索引
- `memorygraph index [path]` — 扫描项目文件并构建代码图谱
- `memorygraph doctor` — 诊断索引健康状态

### 查询
- `memorygraph query <text>` — 全文搜索代码符号
- `memorygraph find <name>` — 按名称查找符号
- `memorygraph callers <name>` — 查找调用者
- `memorygraph callees <name>` — 查找被调用者

### 语义
- `memorygraph semantic stats` — 语义分析统计
- `memorygraph semantic search <query>` — 嵌入向量语义搜索
- `memorygraph semantic patterns` — 设计模式检测

### 服务
- `memorygraph serve` — 启动 Web + MCP 服务器

## 核心 API

### EmbeddingGenerator
`memorygraph.semantic.embeddings.EmbeddingGenerator`

生成代码符号的向量嵌入（384 维，all-MiniLM-L6-v2）。

```python
from memorygraph.semantic.embeddings import EmbeddingGenerator

gen = EmbeddingGenerator()
if gen.is_available:
    vec = gen.generate("function_name", "def foo(x): ...", "docstring context")
    # vec: np.ndarray, shape (384,) float32
```

**方法：**
- `generate(name, signature='', context='') -> Optional[np.ndarray]` — 生成单个符号的嵌入
- `generate_batch(symbols: List[Symbol]) -> List[Optional[np.ndarray]]` — 批量生成嵌入
- `search(query_vec, stored, top_k=10) -> List[dict]` — 余弦相似度搜索
- `hybrid_search(query_vec, fts_results, vec_results) -> List[dict]` — 混合搜索（FTS + 向量）
- `is_available -> bool` — 模型是否可用

### StorageManager
`memorygraph.storage.manager.StorageManager`

统一的存储管理器，封装 SQLite/PostgreSQL 后端。

```python
from memorygraph.storage.manager import StorageManager

mgr = StorageManager("path/to/.memorygraph/memorygraph.db")
mgr.upsert(symbols)          # 插入或更新符号
results = mgr.search("auth") # 全文搜索
node = mgr.get_node("MyClass") # 获取单个节点
callers = mgr.get_callers("my_func") # 获取调用者
callees = mgr.get_callees("my_func") # 获取被调用者
```

### ParsingPipeline
`memorygraph.parsing.pipeline.ParsingPipeline`

4 阶段解析管道：Detect → Parse → Extract → Resolve

```python
from memorygraph.parsing.pipeline import ParsingPipeline

pipeline = ParsingPipeline()
symbols = pipeline.parse_file("src/main.py")
# Returns: List[Symbol] with edges (calls, references, etc.)
```

### MCP 服务器
`memorygraph.mcp.server`

MCP (Model Context Protocol) 服务，暴露 20 个工具给 AI 编程助手。分为静态图谱查询、语义写入和交互沉淀三大类。

**传输端点：**
- `POST /mcp/tools` — 列出可用工具
- `POST /mcp/call` — 调用工具
- `GET /health` — 健康检查
- `GET /metrics` — Prometheus 指标

#### 静态图谱查询（10 个工具）

| Tool | 参数 | 说明 |
|------|------|------|
| `memorygraph_search` | `query`, `limit?` | 符号名搜索，返回匹配符号及位置 |
| `memorygraph_callers` | `symbol`, `depth?`, `file_path?` | 查找调用该符号的函数 |
| `memorygraph_callees` | `symbol`, `depth?`, `file_path?` | 查找该符号调用的函数 |
| `memorygraph_impact` | `symbol`, `depth?` | 分析修改影响范围，返回下游调用链 |
| `memorygraph_node` | `symbol`, `file_path?` | 获取符号详细信息 |
| `memorygraph_context` | `task`, `limit?` | 按任务描述查找相关符号和入口点，自动附加语义数据 |
| `memorygraph_diff` | `diff` | 分析 git diff，返回受影响符号和调用链 |
| `memorygraph_semantic_context` | `file?`, `symbol?` | 获取文件/符号的语义上下文（标注、洞察、问题） |
| `memorygraph_semantic_search` | `query`, `limit?`, `hybrid?` | 向量语义搜索（all-MiniLM-L6-v2），回退到 FTS5 |
| `memorygraph_hot_symbols` | `limit?` | 查询历史中最常访问的符号（L5-4：自增长图谱） |

#### 语义写入（3 个工具）— L5 交互沉淀核心

| Tool | 参数 | 说明 |
|------|------|------|
| `memorygraph_annotate` | `file_path`, `symbol`, `summary`, `kind?`, `design_intent?`, `pitfalls?` | 为符号写入语义标注——记录用途、设计意图、陷阱 |
| `memorygraph_add_insight` | `file_path`, `insight`, `related_symbols?` | 记录设计洞察——跨模块的模式、权衡、约定 |
| `memorygraph_add_unknown` | `file_path`, `symbol`, `question`, `context?` | 记录开放问题——追踪「已知的未知」 |

#### 语义查询（2 个工具）

| Tool | 参数 | 说明 |
|------|------|------|
| `memorygraph_annotations` | `file?`, `symbol?` | 获取人工标注，可按文件/符号过滤 |
| `memorygraph_unknowns` | `limit?` | 获取开放问题，按引用频率排序 |
| `memorygraph_insights` | `limit?` | 获取设计洞察和架构观察 |

#### 索引保鲜（2 个工具）

| Tool | 参数 | 说明 |
|------|------|------|
| `memorygraph_check_freshness` | — | 检查代码索引是否最新，报告新增/变更/未变更文件数 |
| `memorygraph_auto_sync` | — | 手动触发索引新鲜度检查和修复 |

#### 交互沉淀（2 个工具）— L5-3 对话 → 语义

| Tool | 参数 | 说明 |
|------|------|------|
| `memorygraph_ingest_conversation` | `text`, `file_path?` | 从 Claude Code 对话转录提取语义标注 |
| `memorygraph_save_conversation` | `text` | 保存对话转录到 `.memorygraph/conversations/` |

### IR 数据类型
`memorygraph.parsing.ir`

统一的中间表示（IR），解析层的唯一输出。

```python
@dataclass
class Symbol:
    name: str              # 符号名
    qualified_name: str    # 完全限定名
    kind: SymbolKind       # function | method | class | variable | module
    signature: str         # 函数/方法签名
    span: Span             # 源码位置
    file_path: str         # 所属文件
    docstring: Optional[str]
    decorators: List[str]

@dataclass
class Edge:
    source: str            # 源符号 qualified_name
    target: str            # 目标符号 qualified_name
    kind: EdgeKind         # calls | references | inherits | imports
    target_span: Optional[Span]
```

## 配置参考

### config.json

```json
{
  "storage": {
    "backend": "sqlite",         // sqlite | postgresql
    "database": ".memorygraph/memorygraph.db"
  },
  "parsing": {
    "max_file_size_mb": 10,
    "exclude_patterns": ["node_modules/", ".git/", "__pycache__/"],
    "include_languages": ["python", "typescript", "javascript", "rust", "go", "java", "csharp"]
  },
  "semantic": {
    "model_name": "all-MiniLM-L6-v2",
    "model_path": null,          // 覆盖默认模型路径
    "batch_size": 32
  },
  "server": {
    "host": "127.0.0.1",
    "port": 8765,
    "cors_origins": ["*"]
  }
}
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MEMORYGRAPH_HOME` | `.memorygraph` | 数据和配置目录 |
| `HF_ENDPOINT` | `https://huggingface.co` | HuggingFace 端点（可用镜像） |
| `HF_HUB_OFFLINE` | `0` | 设为 `1` 强制离线模式 |
| `SENTENCE_TRANSFORMERS_HOME` | `~/.cache/sentence-transformers` | 模型缓存目录 |
