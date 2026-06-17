# memorygraph User Guide

## What is memorygraph?

memorygraph builds a **knowledge graph** of your codebase — it indexes every symbol
(function, class, method, variable), tracks their relationships (callers/callees),
and provides semantic search via embeddings. Use it for code exploration, impact
analysis, and understanding unfamiliar repositories.

Key features:
- **Multi-language**: Python, TypeScript, JavaScript, Go, Rust, Java, C#
- **Fast indexing**: 280+ f/s single-process, 300+ f/s multi-process (1000-file benchmark)
- **Full-text + semantic search**: Symbol search + task-based code discovery
- **Call graph traversal**: Find callers and callees up to N levels deep
- **Web UI + API**: Built-in HTTP server with REST API and Prometheus metrics
- **MCP server**: Integrates with Claude Code, Codex, and other AI coding tools

---

## Quick Start

```bash
# Install
pip install memorygraph

# Initialize a project
cd my-project
memorygraph init

# Index the codebase
memorygraph index

# Search for symbols
memorygraph query "authentication"

# Start web UI + API
memorygraph serve --web

# Use with Claude Code (MCP)
memorygraph serve    # stdio MCP mode
```

Open `http://localhost:8765` for the web UI.

---

## CLI Command Reference

### `memorygraph init`

Initialize memorygraph in a project directory. Creates `.memorygraph/` with the
SQLite database and configuration.

```
memorygraph init [--project-root PATH]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--project-root` | `.` | Project root directory |

### `memorygraph uninit`

Remove memorygraph from a project. Deletes `.memorygraph/` directory and all
indexed data.

```
memorygraph uninit [--project-root PATH] [--force]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--project-root` | `.` | Project root directory |
| `--force` | `false` | Skip confirmation prompt |

### `memorygraph index`

Parse and index all source files. Uses parallel processing for speed.

```
memorygraph index [--project-root PATH] [--embed]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--project-root` | `.` | Project root directory |
| `--embed` | `false` | Generate vector embeddings after indexing |

### `memorygraph sync`

Incremental sync — only re-parses changed files. Much faster than `index` for
large projects where only a few files changed.

```
memorygraph sync [--project-root PATH] [--analyze/--no-analyze]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--project-root` | `.` | Project root directory |
| `--analyze` | `false` | Run semantic analysis on synced files |

### `memorygraph watch`

Watch project files and auto-sync on changes (daemon mode, Linux only).

```
memorygraph watch [--project-root PATH]
memorygraph watch --stop     # Stop running watcher
```

### `memorygraph query`

Search and explore the knowledge graph. Supports multiple sub-commands.

```
memorygraph query <name>            # Search symbols by name
memorygraph query search <query>    # Full-text search (FTS5)
memorygraph query callers <symbol>  # Find callers of a symbol
memorygraph query callees <symbol>  # Find callees of a symbol
```

Options (shared):
| Option | Default | Description |
|--------|---------|-------------|
| `--project-root` | `.` | Project root directory |
| `--limit` | `20` | Maximum results |
| `--file` | — | Filter to specific file |
| `--format` | `table` | Output format: `table`, `json`, `csv` |

Examples:
```bash
# Find all callers of a function
memorygraph query callers "src.auth.login"

# Find everything a module calls
memorygraph query callees "src.main" --limit 50

# Export search results as JSON
memorygraph query search "error handling" --format json
```

### `memorygraph export`

Export the knowledge graph for external analysis.

```
memorygraph export [--project-root PATH] [--format FORMAT] [--output FILE]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--project-root` | `.` | Project root directory |
| `--format` | `json` | Export format: `json`, `dot` (Graphviz) |
| `--output` | stdout | Output file path |

### `memorygraph serve`

Start the HTTP server with web UI and REST API, or MCP stdio server.

```
memorygraph serve --web [--port PORT] [--background/--stop]
memorygraph serve          # MCP stdio mode (no --web flag)
```

| Option | Default | Description |
|--------|---------|-------------|
| `--web` | — | Start HTTP server mode |
| `--port` | `8765` | HTTP listen port |
| `--background` | `false` | Run as daemon (Linux only) |
| `--stop` | `false` | Stop background daemon |
| `--project-root` | `.` | Project root directory |

### `memorygraph doctor`

Diagnose memorygraph health. Checks database integrity, file index freshness,
and configuration.

```
memorygraph doctor [--project-root PATH]
```

### `memorygraph status`

Show index statistics: file count, symbol count, database size.

```
memorygraph status [--project-root PATH]
```

### `memorygraph analyze`

Run language-specific analyzers over indexed code.

```
memorygraph analyze [--project-root PATH] [--file PATH] [--analyzer NAME]
```

### `memorygraph hook`

Install or uninstall git hooks for auto-sync on commit.

```
memorygraph hook install    # Install pre-commit hook
memorygraph hook uninstall  # Remove pre-commit hook
```

---

## Web API Reference

Base URL: `http://localhost:8765`

### `GET /`
Web UI — interactive code graph explorer.

### `GET /health`

Server health and statistics.

**Response:**
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

Prometheus-format metrics endpoint. Compatible with Prometheus and Grafana.

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

Index statistics (same data as `memorygraph status` CLI).

**Response:**
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

Full-text search (FTS5) across all indexed symbols.

**Parameters:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| `q` | (required) | Search query (FTS5 syntax) |
| `limit` | `20` | Maximum results |
| `file_path` | — | Filter to specific file |

**Response:**
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

Look up a specific symbol by its fully qualified name.

**Example:** `GET /api/node/auth.authenticate`

**Response:**
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

Get the call graph around a symbol.

**Parameters:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| `symbol` | — | Starting symbol (qualified name) |
| `depth` | `1` | Traversal depth (1-5) |

**Response:**
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

Find all callers of a symbol (recursive).

**Example:** `GET /api/callers/auth.authenticate?depth=2`

### `GET /api/callees/<symbol>?depth=<n>`

Find all symbols called by a symbol (recursive).

**Example:** `GET /api/callees/src.main?depth=2`

### `GET /api/impact/<symbol>?max_depth=<n>`

Analyze the blast radius of changing a symbol. Returns all transitive callees.

### `GET /api/semantic-search?q=<task>&limit=<n>`

Multi-word semantic search — describe a task, find relevant code.

**Example:** `GET /api/semantic-search?q=user password reset email`

### `GET /api/events`

Server-Sent Events (SSE) stream for real-time index updates.

---

## MCP Server Usage

memorygraph can run as a Model Context Protocol (MCP) server, providing tools
for AI coding assistants like Claude Code, Codex, and Gemini CLI.

### Setup

Add to your AI tool's MCP configuration:

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

### Available MCP Tools

| Tool | Description |
|------|-------------|
| `memorygraph_search` | Full-text symbol search |
| `memorygraph_node` | Get symbol details by qualified name |
| `memorygraph_callers` | Find callers of a symbol |
| `memorygraph_callees` | Find callees of a symbol |
| `memorygraph_impact` | Analyze change impact radius |
| `memorygraph_semantic_search` | Task-based semantic code search |

### Available MCP Write Tools

**Write tools** — contribute back to the knowledge graph (the "use-and-accumulate" loop):

| Tool | Description |
|------|-------------|
| `memorygraph_annotate` | Write an annotation for a symbol — what it does, design intent, pitfalls |
| `memorygraph_add_insight` | Record a design insight or architectural observation |
| `memorygraph_add_unknown` | Record an open question — tracks what we still need to figure out |

When Claude Code calls these write tools during a session, it builds up the
semantic knowledge graph incrementally. Each session benefits from everything
learned previously.

---

## Semantic Layer: Use, Learn, Accumulate

memorygraph's semantic layer stores **human-level understanding** of code,
accumulated over time through interactive use.

### Concepts

| Concept | What it captures |
|---------|-----------------|
| **Annotation** | Per-symbol: what it does, design intent, pitfalls |
| **Insight** | Cross-cutting: patterns, trade-offs, conventions |
| **Unknown** | Open questions: gaps in understanding to resolve later |
| **Semantic Document** | Per-file JSON in `.memorygraph/semantic/<hash>.json` |

### How the loop works

```
1. Static index (memorygraph index)      → syntax graph baseline
2. Claude Code session                   → queries graph, reads code
3. Claude calls MCP write tools          → annotate, add_insight, add_unknown
4. Semantic store accumulates knowledge  → .memorygraph/semantic/*.json
5. Next session gains richer context     → the graph grows smarter
```

All semantic data is **merge-safe**: annotations for the same symbol are
upserted (latest wins), while insights and unknowns are appended.

### Querying the semantic layer

```bash
# CLI
memorygraph query annotations --symbol auth.login
memorygraph query unknowns --limit 20
memorygraph query insights
```

---

## Deployment

### Systemd (Linux)

Create `/etc/systemd/system/memorygraph.service`:

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

Pre-built image available on Docker Hub:

```bash
# Pull and run as daemon with data persistence
docker pull zhangyiwen5512/memorygraph:latest
docker run -d --restart unless-stopped \
  -p 8765:8765 \
  -v $(pwd):/project \
  -v $(pwd)/.memorygraph:/home/memorygraph/.memorygraph \
  zhangyiwen5512/memorygraph

# Init + index before first use
docker run -v $(pwd):/project zhangyiwen5512/memorygraph init
docker run -v $(pwd):/project zhangyiwen5512/memorygraph index
```

Or use `docker-compose` (see [Deployment Guide](DEPLOYMENT.md)).

### Nginx Reverse Proxy

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

        # SSE support
        proxy_buffering off;
        proxy_cache off;
    }
}
```

### CI/CD Integration (GitHub Actions)

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

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MEMORYGRAPH_DB_PATH` | `.memorygraph/memorygraph.db` | SQLite database path |
| `MEMORYGRAPH_PORT` | `8765` | Web server port |
| `MEMORYGRAPH_LOG_LEVEL` | `INFO` | Logging level (DEBUG/INFO/WARNING/ERROR) |
| `DATABASE_URL` | — | PostgreSQL connection string (for pg backend) |

### Project Structure

```
my-project/
├── .memorygraph/
│   ├── memorygraph.db      # SQLite database
│   └── file_hashes.json    # File hash cache for incremental sync
├── src/                     # Your source code
└── pyproject.toml
```

---

## Performance Tuning

### Indexing Large Projects (5000+ files)

```bash
# Use batch mode for very large projects
memorygraph index --force

# Or do incremental sync after initial index
memorygraph sync
```

Typical performance (validated on Linux, Intel i7, SSD):
| Repo Size | Files | Index Time | Rate |
|-----------|-------|------------|------|
| Small | 100 | <0.5s | ~500 f/s |
| Medium | 1,000 | ~2s | ~500 f/s |
| Large | 10,000 | ~20s | ~500 f/s |

### Memory Usage

memorygraph uses ~50-100 MB RAM for typical projects (<1000 files). For very
large codebases (>10,000 files), allocate 512 MB+ and use PostgreSQL backend.

### PostgreSQL Backend

For teams or large codebases, use PostgreSQL instead of SQLite:

```bash
export DATABASE_URL="postgresql://user:pass@localhost:5432/memorygraph"
memorygraph init
memorygraph index
```

---

## Supported Languages

| Language | File Extensions | Parser |
|----------|----------------|--------|
| Python | `.py` | tree-sitter-python |
| TypeScript | `.ts`, `.tsx` | tree-sitter-typescript |
| JavaScript | `.js`, `.jsx` | tree-sitter-typescript |
| Go | `.go` | tree-sitter-go |
| Rust | `.rs` | tree-sitter-rust |
| Java | `.java` | tree-sitter-java |
| C# | `.cs` | tree-sitter-c-sharp |

---

## Troubleshooting

### "No source files found"

Ensure your project contains source files in recognized languages. Use
`memorygraph doctor` to diagnose.

### "Database is locked"

Only one writer can access the SQLite database at a time. Stop any running
`memorygraph serve` or `memorygraph watch` processes before indexing.

### "Model not cached" (semantic search)

Semantic search requires the `all-MiniLM-L6-v2` model from HuggingFace.
On first use, download it manually:

```bash
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
```

If behind a proxy, configure `HTTP_PROXY`/`HTTPS_PROXY` environment variables.

### Slow indexing on first run

First-time indexing is CPU-bound by tree-sitter parsing. Subsequent runs with
`memorygraph sync` only re-parse changed files.

---

## Development

```bash
git clone https://github.com/memorygraph/memorygraph
cd memorygraph
make dev         # pip install -e ".[dev]"
make test        # pytest
make lint        # ruff check
make typecheck   # mypy
make deadcode    # vulture
make bench       # stress test (1000 files)
make ci          # full CI pipeline
```

## Reference

- **[API Reference](API_REFERENCE.md)** — Public API surface: EmbeddingGenerator, StorageManager, ParsingPipeline, MCP Server, IR types, and configuration
- **[Deployment Guide](DEPLOYMENT.md)** — Pip/source/Docker install, model download (HuggingFace mirrors + SOCKS proxy), PostgreSQL, production deployment

---

## Performance

memorygraph is optimized for speed. Performance data from v5.15.0-dev (iter-67):

| Benchmark | Files | Throughput | Parse | Upsert | Memory Δ |
|-----------|-------|-----------|-------|--------|----------|
| Raw pipeline (1000) | 1,000 | **280 f/s** | 301 f/s | 0.25s | — |
| Raw pipeline (5000) | 5,000 | **349 f/s** | 376 f/s | 1.03s | +78 MB |
| Parallel (1000, 16 cores) | 1,000 | **4,000+ f/s** | — | — | per-process |

Key optimizations:
- **Query caching**: Compiled tree-sitter queries reused across files
- **I/O prefetch**: Batch file reads before parsing
- **Extractor reuse**: Single extractor instance per language
- **Multi-process**: ProcessPoolExecutor for CPU-bound work
