# memorygraph

[![GA](https://img.shields.io/badge/status-GA-brightgreen)]()
[![Version](https://img.shields.io/badge/version-0.0.1-blue)]()
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)]()
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey)]()
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen)]()
[![Ruff](https://img.shields.io/badge/lint-ruff-0-brightgreen)]()
[![Mypy](https://img.shields.io/badge/typecheck-mypy-0-brightgreen)]()
[![Bandit](https://img.shields.io/badge/security-bandit-0%20High%2FCritical-brightgreen)]()

A local code knowledge graph tool with a semantic incremental layer — "use, learn, accumulate" as you code.

**100% local, zero external API keys required.**

> **v0.0.1** | Coverage: 99.9% | Tests: 1304 | Languages: 7 | CLI Commands: 12 | MCP Tools: 20 | Semantic Search: ✅ | Performance: 224 files/s

## Overview

memorygraph builds a static knowledge graph from your source code using
[tree-sitter](https://tree-sitter.github.io/) AST parsing, then layers human-curated
semantic annotations on top. The result is a queryable, always-up-to-date code
intelligence database that grows richer the more you use it.

### Two-layer architecture

| Layer | Engine | Purpose |
|-------|--------|---------|
| **Static graph** | tree-sitter + SQLite (or PostgreSQL) | Deterministic symbol/edge extraction from AST |
| **Semantic layer** | JSON documents | Human-curated annotations, design intent, known pitfalls |

The static layer is the backbone — it never changes based on semantics. The semantic
layer is append-only advisory data that enriches queries without compromising determinism.

## Performance

| Metric | Value |
|--------|-------|
| Index speed | **>=150 files/s** (1000 Python files verified) |
| Query latency (P50) | < 1ms |
| Query latency (P99) | < 3ms |
| Test coverage | 100% |
| Memory (indexing) | ~200 MB per 1000 files |

**Verified on:** black (337 files), flask (83 files), 1000-file synthetic stress test.

Multi-core parallel parsing via `ProcessPoolExecutor` with batched DB transactions (2x+ faster than per-file commits).

## Language Support

| Feature | Python | TypeScript | JavaScript | Go | Rust | Java | C# |
|---------|--------|------------|------------|----|------|------|-----|
| Symbol extraction | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Call graph | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Full-text search | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Semantic analysis | ✅ | --- | --- | --- | --- | --- | --- |
| Vector embeddings | ✅ | --- | --- | --- | --- | --- | --- |

7 languages built-in, zero configuration.

Extensible via the [Plugin system](#plugin-system) — add custom languages and analyzers.

## Installation

### Docker (Recommended)

```bash
docker pull zhangyiwen5512/memorygraph:latest
docker run -d --restart unless-stopped \
  -p 8765:8765 \
  -v $(pwd):/project \
  -v $(pwd)/.memorygraph:/home/memorygraph/.memorygraph \
  zhangyiwen5512/memorygraph
```

See [Deployment Guide](docs/en/DEPLOYMENT.md) for docker-compose and advanced options.

### pip / Source

```bash
git clone https://github.com/zhangyiwen5512/memorygraph.git
cd memorygraph
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

### Requirements

- Python 3.10+
- Platform-specific tree-sitter runtime (installed automatically via pip)
- Optional: `radon>=6.0` for complexity analysis

## Quick Start

```bash
# Initialize in a project directory
memorygraph init

# Full index
memorygraph index

# Check status
memorygraph status

# Search symbols
memorygraph query "authentication"

# Find context for a task
memorygraph context "add user login"

# Show affected symbols
memorygraph affected src/auth.py

# Detect design patterns
memorygraph patterns

# Show git history for a function
memorygraph git-history "login"

# List installed plugins
memorygraph plugins list

# Extract annotations from Claude Code conversations
memorygraph extract-from-conversation --input conversation.json
```

## CLI Commands

### Project Management

| Command | Description |
|---------|-------------|
| `memorygraph init` | Initialize `.memorygraph/` directory and database |
| `memorygraph uninit` | Remove `.memorygraph/` and all indexed data, clean MCP config |
| `memorygraph install` | Register MCP server in `~/.claude.json` |

### Indexing

| Command | Description |
|---------|-------------|
| `memorygraph index` | Full re-index of all source files with multi-core parallel parsing |
| `memorygraph sync` | Incremental sync — only re-parses changed files (SHA256 hash check) |
| `memorygraph watch` | Start file watcher — auto-syncs on file save |

### Querying & Analysis

| Command | Description |
|---------|-------------|
| `memorygraph status` | Show statistics: files, symbols, edges, semantic coverage |
| `memorygraph query <text>` | Full-text search for symbols (FTS5) |
| `memorygraph files` | List all indexed files with metadata |
| `memorygraph context <task>` | Find relevant symbols and entry points for a task |
| `memorygraph affected <file...>` | Show symbols affected by file changes (supports `--from-diff`) |
| `memorygraph export` | Export graph as Cytoscape.js JSON |
| `memorygraph patterns` | Detect design patterns (Singleton, Factory, Observer, Strategy, Decorator, Repository) |
| `memorygraph git-history <symbol>` | Trace symbol-level changes through git history (`git log -L`) |

### Semantic

| Command | Description |
|---------|-------------|
| `memorygraph semantic-ingest` | Ingest semantic annotations for files |
| `memorygraph analyze` | Run complexity analysis (requires radon) |
| `memorygraph smells` | List detected code smells |
| `memorygraph metrics` | Show complexity metrics |
| `memorygraph extract-from-conversation` | Extract annotations from Claude Code JSON exports (heuristic, no LLM) |

### Serving & Plugins

| Command | Description |
|---------|-------------|
| `memorygraph serve --mcp` | Start MCP stdio server |
| `memorygraph serve --web` | Start web UI (interactive Cytoscape.js force graph) |
| `memorygraph plugins list` | List built-in and third-party plugins |

### Options

Most commands accept `--project-root <path>` (default: current directory):

```bash
memorygraph status --project-root /path/to/project
memorygraph index --project-root /path/to/project
```

### Automatic Exclusion

Always excluded: `node_modules`, `vendor`, `dist`, `build`, `target`, `.venv`, `.next`, `__pycache__`, `.memorygraph`, `.git`, `.idea`, `.vscode`

Patterns from `.gitignore` are respected.

## MCP (Model Context Protocol) Tools

memorygraph exposes 11 MCP tools via `memorygraph serve --mcp`:

### Static Graph Tools

| Tool | Description |
|------|-------------|
| `memorygraph_context` | Given a task description, returns entry points, related symbols with callers/callees. **Auto-attaches semantic data** when available. |
| `memorygraph_search` | Search for symbols by name with locations. |
| `memorygraph_callers` | List callers of a symbol. Supports `file_path` to disambiguate same-named symbols. |
| `memorygraph_callees` | List callees of a symbol. Supports `file_path` to disambiguate same-named symbols. |
| `memorygraph_impact` | Analyze downstream impact of changing a symbol. |
| `memorygraph_node` | Get symbol details. Supports `file_path` to disambiguate same-named symbols across files. |
| `memorygraph_diff` | Parse a git diff, return affected symbols and their call chains. |

### Semantic Tools

| Tool | Description |
|------|-------------|
| `memorygraph_semantic_context` | Get semantic annotations, insights, unknowns for a file or symbol. |
| `memorygraph_annotations` | Get human-written annotations, optionally filtered by file or symbol. |
| `memorygraph_unknowns` | Get open questions, sorted by reference frequency. |
| `memorygraph_insights` | Get design insights across documented modules. |

### Tool Input/Output Examples

#### `memorygraph_context`

Input:
```json
{
  "task": "implement user authentication",
  "limit": 10
}
```

Output:
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

Input:
```json
{
  "diff": "diff --git a/src/auth.py b/src/auth.py\n--- a/src/auth.py\n+++ b/src/auth.py\n..."
}
```

Output:
```json
{
  "changed_files": ["src/auth.py"],
  "affected_symbols": ["login", "verify_password", "AuthManager"],
  "call_chains": {
    "login": ["RequestHandler.authenticate", "SessionManager.create"]
  }
}
```

## Design Pattern Detection

Static heuristic detection of 6 common patterns — no external dependencies:

| Pattern | Detection Signal |
|---------|-----------------|
| **Singleton** | `_instance` attribute or `get_instance()` method |
| **Factory** | Name contains Factory/Builder, or returns object of same type |
| **Observer** | `subscribe`/`on_`/`add_listener` + `notify`/`emit`/`trigger` methods |
| **Strategy** | Abstract base class with 2+ concrete implementations |
| **Decorator** | Name contains Decorator/Wrapper, or `__init__` takes wrappee parameter |
| **Repository** | Name contains Repository/Store/DAO, with CRUD methods |

Detection is conservative-biased — prefers false positives over missing real patterns.
Use `memorygraph patterns` to scan your project.

## Plugin System

Third-party languages and analyzers register via `pyproject.toml`:

```toml
[project.entry-points."memorygraph.plugins"]
kotlin = "memorygraph_kotlin:KotlinPlugin"
```

Two plugin types:
- **LanguagePlugin**: provides AST extraction for a language
- **AnalyzerPlugin**: provides additional analysis (smells, metrics, patterns)

List installed plugins: `memorygraph plugins list`

## Semantic Layer

The semantic layer stores human-curated understanding as JSON documents in
`.memorygraph/semantic/<file-path-hash>.json`. Documents are **append-only** — merging
never deletes existing annotations. Uses `filelock` for concurrent write safety.

### Semantic Document Schema

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

### Adding Semantic Data

```bash
# Manual ingestion
memorygraph semantic-ingest --file src/auth.py --summary "Authentication module"

# Extract from Claude Code conversations
memorygraph extract-from-conversation --input conversation.json

# Automatic via PostToolUse hook (add to .claude/settings.json):
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

## Storage

All data is stored locally in `.memorygraph/`:

```
.memorygraph/
├── memorygraph.db          # SQLite (schema + FTS5 + data)
└── semantic/               # Semantic JSON documents
    ├── <hash1>.json
    └── <hash2>.json
```

### PostgreSQL Support (Experimental)

Set `DATABASE_URL` to use PostgreSQL instead of SQLite:

```bash
export DATABASE_URL="postgresql://user:pass@localhost/memorygraph"
memorygraph init
memorygraph index
```

Uses abstract `AbstractRepository` with `SQLiteRepository` (default) and
`PostgreSQLRepository` backends. FTS via PostgreSQL `tsvector` + GIN index.

### Database Schema

- `files` — file metadata with SHA256 hash for incremental sync
- `functions`, `methods`, `classes`, `interfaces`, `type_aliases`, `variables` — symbol tables
- `edges` — call relationships with composite indexes `(target, kind)` + `(source, kind)` for fast graph traversal
- `fts_index` — FTS5 virtual table with batch insert optimization

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run all tests (763 tests, 99% coverage)
pytest

# Run specific test file
pytest tests/test_semantic.py -v

# Coverage report
python -m coverage run --source=src/memorygraph -m pytest && python -m coverage report
```

## Known Limitations

- Web server is single-threaded (`http.server`)
- Export caps at 500 nodes (browser memory)
- Pattern detection is heuristic (conservative-biased; some false positives)
- PostgreSQL backend requires `psycopg2` (not auto-installed)
- `memorygraph watch` is a stub — use `memorygraph sync` for manual incremental updates
- Design pattern detection may produce false positives (by design — prefers recall over precision)

## License

MIT
