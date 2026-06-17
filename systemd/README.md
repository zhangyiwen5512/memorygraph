# memorygraph systemd Integration

Template unit files for running memorygraph daemons under systemd.

## Installation

```bash
# Copy unit files to systemd user directory
mkdir -p ~/.config/systemd/user/
cp systemd/*.service ~/.config/systemd/user/

# Reload systemd
systemctl --user daemon-reload

# Enable and start file watcher for your project
systemctl --user enable --now memorygraph-watch@/home/user/myproject.service

# Enable and start web UI + MCP server
systemctl --user enable --now memorygraph-serve@/home/user/myproject.service

# Enable lingering (keep services running after logout)
loginctl enable-linger
```

## Services

| Service | Description | Port |
|---------|-------------|------|
| `memorygraph-watch@.service` | File watcher — auto-syncs index on file changes | — |
| `memorygraph-serve@.service` | Web UI + MCP server | 8765 (default) |

Both are **template units** (`@`): the instance name is the project root path.

## Management

```bash
# Status
systemctl --user status memorygraph-watch@/path/to/project.service

# Logs
journalctl --user -u memorygraph-watch@/path/to/project.service -f

# Restart after config change
systemctl --user restart memorygraph-watch@/path/to/project.service

# Stop
systemctl --user stop memorygraph-watch@/path/to/project.service
```

## Security

Units run with `ProtectSystem=strict` and `NoNewPrivileges=yes`. Only
`.memorygraph/` is writable; project source is read-only.

## Crash Recovery

`Restart=on-failure` with 5-second backoff ensures automatic recovery from
crashes. `StartLimitBurst=5` prevents infinite restart loops.
