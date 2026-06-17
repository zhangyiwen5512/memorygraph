# memorygraph API Reference

> Auto-generated from source docstrings. Covers all public API surfaces.

## Module Index

- **`memorygraph.mcp.server`** — MCP server — exposes memorygraph tools via Model Context Protocol.
- **`memorygraph.web.api`** — REST API handlers for memorygraph web server.
- **`memorygraph.web.renderer`** — Cytoscape.js interactive HTML renderer with annotation editing.
- **`memorygraph.web.server`** — HTTP server with SSE for memorygraph.
- **`memorygraph.storage.backend`** — Storage backend abstraction — SQLite (default) and PostgreSQL support.
- **`memorygraph.storage.cache`** — Thread-safe LRU cache for graph queries.
- **`memorygraph.storage.connection`** — Database connection management.
- **`memorygraph.storage.manager`** — StorageManager — The sole external entry point for the storage layer.
- **`memorygraph.storage.pg_repository`** — PostgreSQL storage backend — psycopg2 + tsvector FTS.
- **`memorygraph.storage.repositories`** — Repository classes for individual table operations.
- **`memorygraph.storage.schema`** — SQLite schema definitions and initialization.
- **`memorygraph.parsing.batch`** — Batch parallel parser — asyncio + ProcessPoolExecutor (multiprocessing bypasses GIL).
- **`memorygraph.parsing.detector`** — Language detector — file extension → LanguageConfig.
- **`memorygraph.parsing.extractor`** — IRExtractor — converts tree-sitter AST to unified IR Symbols + Edges.
- **`memorygraph.parsing.ir`** — Unified Intermediate Representation (IR) data types.
- **`memorygraph.parsing.pipeline`** — Parsing pipeline — 4 stages in series: Detect → Parse → Extract → Resolve.
- **`memorygraph.parsing.registry`** — Language registry — extension detection + lazy-loaded tree-sitter grammar libraries.
- **`memorygraph.parsing.resolver`** — Cross-file reference resolver — populates Edge.target_span.
- **`memorygraph.parsing.ts_parser`** — Tree-sitter parser wrapper — file byte stream → tree-sitter Tree.
- **`memorygraph.cli.main`** — CLI entry point — memorygraph command-line tool.
- **`memorygraph.cli.shared`** — Shared helpers for CLI command modules.
- **`memorygraph.cli.commands.doctor`** — Doctor command — health checks for memorygraph installation.
- **`memorygraph.cli.commands.indexing`** — Indexing commands: init, uninit, index, sync, watch.
- **`memorygraph.cli.commands.querying`** — Query commands: query, context, files, affected, export.
- **`memorygraph.cli.commands.semantic`** — Semantic analysis CLI commands.
- **`memorygraph.cli.commands.serving`** — Server commands: serve, install.
- **`memorygraph.cli.commands.utils`** — Utility commands: status, plugins.
- **`memorygraph.semantic.analysis`** — Static analysis: complexity, code smells, module role inference.
- **`memorygraph.semantic.conversation`** — Extract semantic annotations from Claude Code conversation exports.
- **`memorygraph.semantic.embeddings`** — Semantic embeddings for code symbols using sentence-transformers.
- **`memorygraph.semantic.models`** — Semantic data models — structured JSON for human-curated code understanding.
- **`memorygraph.semantic.patterns`** — Static design pattern detection.
- **`memorygraph.semantic.store`** — SemanticStore — load/save semantic JSON documents in .memorygraph/semantic/.

## CLI Command Reference

memorygraph provides 12 subcommands, grouped by function:

### Project Management
- `memorygraph init <path>` — Initialize .memorygraph/ directory and SQLite database
- `memorygraph uninit` — Remove .memorygraph/ directory

### Indexing
- `memorygraph index [path]` — Scan project files and build code graph
- `memorygraph doctor` — Diagnose index health status

### Queries
- `memorygraph query <text>` — Full-text search for code symbols
- `memorygraph find <name>` — Find symbol by name
- `memorygraph callers <name>` — Find callers
- `memorygraph callees <name>` — Find callees

### Semantic
- `memorygraph semantic stats` — Semantic analysis statistics
- `memorygraph semantic search <query>` — Vector embedding semantic search
- `memorygraph semantic patterns` — Design pattern detection

### Serving
- `memorygraph serve` — Start Web + MCP server

## Core API

### EmbeddingGenerator
`memorygraph.semantic.embeddings.EmbeddingGenerator`

Generates vector embeddings for code symbols (384-dimensional, all-MiniLM-L6-v2).

```python
from memorygraph.semantic.embeddings import EmbeddingGenerator

gen = EmbeddingGenerator()
if gen.is_available:
    vec = gen.generate("function_name", "def foo(x): ...", "docstring context")
    # vec: np.ndarray, shape (384,) float32
```

**Methods:**
- `generate(name, signature='', context='') -> Optional[np.ndarray]` — Generate embedding for a single symbol
- `generate_batch(symbols: List[Symbol]) -> List[Optional[np.ndarray]]` — Batch generate embeddings
- `search(query_vec, stored, top_k=10) -> List[dict]` — Cosine similarity search
- `hybrid_search(query_vec, fts_results, vec_results) -> List[dict]` — Hybrid search (FTS + vector)
- `is_available -> bool` — Whether the model is available

### StorageManager
`memorygraph.storage.manager.StorageManager`

Unified storage manager, wrapping SQLite/PostgreSQL backends.

```python
from memorygraph.storage.manager import StorageManager

mgr = StorageManager("path/to/.memorygraph/memorygraph.db")
mgr.upsert(symbols)          # Insert or update symbols
results = mgr.search("auth") # Full-text search
node = mgr.get_node("MyClass") # Get a single node
callers = mgr.get_callers("my_func") # Get callers
callees = mgr.get_callees("my_func") # Get callees
```

### ParsingPipeline
`memorygraph.parsing.pipeline.ParsingPipeline`

4-stage parsing pipeline: Detect → Parse → Extract → Resolve

```python
from memorygraph.parsing.pipeline import ParsingPipeline

pipeline = ParsingPipeline()
symbols = pipeline.parse_file("src/main.py")
# Returns: List[Symbol] with edges (calls, references, etc.)
```

### MCP Server
`memorygraph.mcp.server`

MCP (Model Context Protocol) server, exposing 20 tools to AI coding assistants. Divided into three categories: static graph queries, semantic writes, and interaction sedimentation.

**Transport Endpoints:**
- `POST /mcp/tools` — List available tools
- `POST /mcp/call` — Call a tool
- `GET /health` — Health check
- `GET /metrics` — Prometheus metrics

#### Static Graph Queries (10 tools)

| Tool | Parameters | Description |
|------|------|------|
| `memorygraph_search` | `query`, `limit?` | Search symbol names, return matching symbols and locations |
| `memorygraph_callers` | `symbol`, `depth?`, `file_path?` | Find functions that call the given symbol |
| `memorygraph_callees` | `symbol`, `depth?`, `file_path?` | Find functions called by the given symbol |
| `memorygraph_impact` | `symbol`, `depth?` | Analyze impact scope of changes, return downstream call chain |
| `memorygraph_node` | `symbol`, `file_path?` | Get detailed symbol information |
| `memorygraph_context` | `task`, `limit?` | Find related symbols and entry points by task description, auto-attach semantic data |
| `memorygraph_diff` | `diff` | Analyze git diff, return affected symbols and call chains |
| `memorygraph_semantic_context` | `file?`, `symbol?` | Get semantic context for file/symbol (annotations, insights, questions) |
| `memorygraph_semantic_search` | `query`, `limit?`, `hybrid?` | Vector semantic search (all-MiniLM-L6-v2), fallback to FTS5 |
| `memorygraph_hot_symbols` | `limit?` | Query the most frequently accessed symbols in history (L5-4: self-growing graph) |

#### Semantic Writes (3 tools) — L5 Interaction Sedimentation Core

| Tool | Parameters | Description |
|------|------|------|
| `memorygraph_annotate` | `file_path`, `symbol`, `summary`, `kind?`, `design_intent?`, `pitfalls?` | Write semantic annotations for symbols — record purpose, design intent, pitfalls |
| `memorygraph_add_insight` | `file_path`, `insight`, `related_symbols?` | Record design insights — cross-module patterns, trade-offs, conventions |
| `memorygraph_add_unknown` | `file_path`, `symbol`, `question`, `context?` | Record open questions — track "known unknowns" |

#### Semantic Queries (2 tools)

| Tool | Parameters | Description |
|------|------|------|
| `memorygraph_annotations` | `file?`, `symbol?` | Get annotations, filterable by file/symbol |
| `memorygraph_unknowns` | `limit?` | Get open questions, sorted by reference frequency |
| `memorygraph_insights` | `limit?` | Get design insights and architectural observations |

#### Index Freshness (2 tools)

| Tool | Parameters | Description |
|------|------|------|
| `memorygraph_check_freshness` | — | Check if code index is up-to-date, report added/changed/unchanged file counts |
| `memorygraph_auto_sync` | — | Manually trigger index freshness check and repair |

#### Interaction Sedimentation (2 tools) — L5-3 conversation → semantic

| Tool | Parameters | Description |
|------|------|------|
| `memorygraph_ingest_conversation` | `text`, `file_path?` | Extract semantic annotations from Claude Code conversation transcripts |
| `memorygraph_save_conversation` | `text` | Save conversation transcript to `.memorygraph/conversations/` |

### IR Data Types
`memorygraph.parsing.ir`

Unified Intermediate Representation (IR), the sole output of the parsing layer.

```python
@dataclass
class Symbol:
    name: str              # Symbol name
    qualified_name: str    # Fully qualified name
    kind: SymbolKind       # function | method | class | variable | module
    signature: str         # Function/method signature
    span: Span             # Source location (file, start_line, end_line)
    file_path: str         # Owning file path
    docstring: Optional[str]
    decorators: List[str]

@dataclass
class Edge:
    source: str            # Source symbol qualified_name
    target: str            # Target symbol qualified_name
    kind: EdgeKind         # calls | references | inherits | imports
    target_span: Optional[Span]
```

## Configuration Reference

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
    "model_path": null,          // Override default model path
    "batch_size": 32
  },
  "server": {
    "host": "127.0.0.1",
    "port": 8765,
    "cors_origins": ["*"]
  }
}
```

## Environment Variables

| Variable | Default | Description |
|------|--------|------|
| `MEMORYGRAPH_HOME` | `.memorygraph` | Data and configuration directory |
| `HF_ENDPOINT` | `https://huggingface.co` | HuggingFace endpoint (supports mirrors) |
| `HF_HUB_OFFLINE` | `0` | Set to `1` to force offline mode |
| `SENTENCE_TRANSFORMERS_HOME` | `~/.cache/sentence-transformers` | Model cache directory |
