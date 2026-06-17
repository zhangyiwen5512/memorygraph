# memorygraph Deployment Guide

## Requirements

| Component | Minimum Version | Recommended |
|-----------|-----------------|-------------|
| Python | 3.10 | 3.11+ |
| pip | 22.0+ | Latest |
| tree-sitter | 0.21+ | 0.22+ |
| SQLite | 3.35+ | 3.40+ |
| Disk Space | 200 MB | 1 GB+ |
| Memory | 512 MB | 2 GB+ |

Optional Dependencies (required for semantic features):

| Component | Use | Notes |
|-----------|-----|-------|
| sentence-transformers | Code embedding vectors | Requires downloading all-MiniLM-L6-v2 model (~90MB) |
| PostgreSQL 14+ | Production backend | Replaces default SQLite |
| PyTorch 2.0+ | GPU-accelerated embeddings | CPU works but slower |

### SQLite vs PostgreSQL

memorygraph uses **SQLite by default** — zero configuration, single file, fast enough for a single user. PostgreSQL is optional and only useful for team-shared graphs.

**SQLite is the right choice if:**
- You're the only user
- You want zero setup
- You don't need concurrent writes

**PostgreSQL is only needed if:**
- Multiple people share the same graph
- You already have a PG instance and prefer it

#### Using an existing PostgreSQL (Docker)

If you have PG running on your host and want to use it from the Docker container:

```bash
docker run \
  --add-host host.docker.internal:host-gateway \
  -e PGHOST=host.docker.internal \
  -e PGPORT=5432 \
  -e PGUSER=your_user \
  -e PGPASSWORD=your_password \
  -e PGDATABASE=your_db \
  -p 8765:8765 -v $(pwd):/project \
  zhangyiwen5512/memorygraph
```

> `host.docker.internal` is Docker's way to reach your host machine from inside a container. Without it, `localhost` inside the container points to the container itself, not your host.

## Installation

### Method 1: Install from PyPI (Recommended)

```bash
pip install memorygraph
```

With semantic features:

```bash
pip install memorygraph[semantic]
```

With PostgreSQL support:

```bash
pip install memorygraph[postgres]
```

Full installation:

```bash
pip install memorygraph[all]
```

### Method 2: Install from Source

```bash
git clone https://github.com/user/memorygraph.git
cd memorygraph
pip install -e .
```

Development mode (with test dependencies):

```bash
pip install -e ".[dev,test]"
```

### Method 3: Docker

Pre-built images are available on Docker Hub: [`zhangyiwen5512/memorygraph`](https://hub.docker.com/r/zhangyiwen5512/memorygraph)

```bash
# Pull the image
docker pull zhangyiwen5512/memorygraph:latest

# Quick start — daemon with Web UI (data persists in ./.memorygraph/)
docker run -d --restart unless-stopped \
  -p 8765:8765 \
  -v $(pwd):/project \
  -v $(pwd)/.memorygraph:/home/memorygraph/.memorygraph \
  zhangyiwen5512/memorygraph

# Initialize a new project
docker run -v $(pwd):/project zhangyiwen5512/memorygraph init

# Index the project
docker run -v $(pwd):/project zhangyiwen5512/memorygraph index

# Query
docker run -v $(pwd):/project zhangyiwen5512/memorygraph query "authentication"

# Start MCP server (stdio mode)
docker run -i -v $(pwd):/project zhangyiwen5512/memorygraph serve --mcp
```

#### Image Variants

| Tag | Description |
|-----|-------------|
| `latest` | Latest stable release (recommended) |
| `0.0.1` | Specific version pin |

#### Mount Points

| Path | Purpose |
|------|---------|
| `/project` | Your codebase (required) |
| `/home/memorygraph/.memorygraph` | Index data persistence (recommended) |

#### docker-compose (SQLite — default)

```bash
# Start serve + Web UI
docker-compose up -d

# Start serve + file watcher (auto re-index on changes)
docker-compose --profile watch up -d
```

#### docker-compose (PostgreSQL — production)

```bash
# Start with PostgreSQL backend
docker-compose --profile postgres up -d

# Initialize with PG backend
docker-compose --profile postgres run --rm memorygraph init --backend postgres --dsn "postgresql://memorygraph:memorygraph@postgres/memorygraph"

# Start with both PG and watcher
docker-compose --profile postgres --profile watch up -d
```

See `docker-compose.yml` in the repository for the full service definitions.

#### Build from Source

```bash
git clone https://github.com/zhangyiwen5512/memorygraph.git
cd memorygraph
docker build -t memorygraph .
docker run -p 8765:8765 -v $(pwd):/project memorygraph
```

## Model Download

memorygraph's semantic search feature requires the `all-MiniLM-L6-v2` model (~90 MB).

### Automatic Download

Automatically downloaded on first use of semantic features:

```bash
memorygraph serve           # Checks model on startup
memorygraph semantic stats  # Triggers download
```

### Manual Download (Offline / Restricted Networks)

**Step 1**: Download the model on a machine with internet access:

```bash
pip install huggingface-hub
hf download sentence-transformers/all-MiniLM-L6-v2 \
  --local-dir ./all-MiniLM-L6-v2 \
  --local-dir-use-symlinks False
```

**Step 2**: Copy the model directory to the target machine in one of these locations:

```bash
# User-level (recommended)
~/.cache/sentence-transformers/all-MiniLM-L6-v2/

# Project-level (managed with the repository)
.memorygraph/models/all-MiniLM-L6-v2/

# System-level
/usr/local/share/sentence-transformers/all-MiniLM-L6-v2/
```

**Step 3**: Verify the model is available:

```bash
memorygraph doctor  # Checks model status
```

### HuggingFace Mirror

If HuggingFace is unreachable (e.g., mainland China), use a mirror:

```bash
export HF_ENDPOINT=https://hf-mirror.com
memorygraph semantic stats  # Download via mirror
```

### SOCKS Proxy Compatibility

If `ALL_PROXY=socks://...` is set, Python's `huggingface_hub` and `sentence-transformers` libraries cannot use SOCKS proxies.

**Solution (verified):**

```bash
# 1. Unset SOCKS proxy (use HTTP proxy or no proxy)
unset ALL_PROXY SOCKS_PROXY all_proxy socks_proxy

# 2. Use HuggingFace mirror (recommended)
export HF_ENDPOINT=https://hf-mirror.com

# 3. Use hf CLI to download the model (auto-detects HTTP proxy or direct connection)
hf download sentence-transformers/all-MiniLM-L6-v2

# 4. Verify
python3 -c "from sentence_transformers import SentenceTransformer;   m = SentenceTransformer('all-MiniLM-L6-v2', local_files_only=True);   print('OK:', m.get_embedding_dimension(), 'dims')"
```

> **Note**: The `hf` CLI (new `huggingface-cli`) uses a different network stack and works more easily through proxies than the Python SDK.

## Quick Start

```bash
# 1. Initialize a project
memorygraph init ./my-project

# 2. Index code
cd my-project
memorygraph index

# 3. Query
memorygraph query "authentication"
memorygraph find MyClass

# 4. Start MCP server
memorygraph serve --mcp
```

## Configuration

Configuration file: `.memorygraph/config.json` (project-level) or `~/.config/memorygraph/config.json` (user-level)

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

## PostgreSQL Configuration

```bash
# Install PostgreSQL support
pip install memorygraph[postgres]

# Create database
createdb memorygraph

# Initialize
memorygraph init --backend postgres --dsn "postgresql://user:pass@localhost/memorygraph"
```

## Development Environment

```bash
# Clone the repository
git clone https://github.com/user/memorygraph.git
cd memorygraph

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install development dependencies
pip install -e ".[dev,test,all]"

# Run tests
pytest

# Code quality checks
ruff check src/
mypy src/
vulture src/ --min-confidence 80
```

## Production Deployment

### Using waitress (Windows/Linux)

```bash
pip install waitress
waitress-serve --host 0.0.0.0 --port 8765 memorygraph.web.app:app
```

### Using gunicorn (Linux/macOS)

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:8765 memorygraph.web.app:app
```

### systemd Service

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

## Troubleshooting

### Model Download Failure

```bash
# Check network
curl -I https://huggingface.co

# Use mirror
export HF_ENDPOINT=https://hf-mirror.com

# Manual download (see above)
```

### tree-sitter Compilation Error

```bash
# Requires a C compiler
sudo apt install build-essential  # Debian/Ubuntu
brew install gcc                   # macOS

pip install --no-binary tree-sitter tree-sitter
```

### SQLite Version Too Low

```bash
# Check version
python3 -c "import sqlite3; print(sqlite3.sqlite_version)"

# Upgrade (requires 3.35+)
pip install pysqlite3-binary
```

### Permission Issues

```bash
# Linux: Ensure the user has write permission to the project directory
chown -R $USER:$USER /path/to/project

# macOS: Check Privacy & Security settings
```
