"""End-to-end MCP server test using real subprocess communication.

Tests the full flow: init → index → serve --mcp → JSON-RPC tool call → stop.
Uses the actual MCP stdio protocol (JSON-RPC 2.0).
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_MEMORYGRAPH_BIN = shutil.which("memorygraph") or sys.executable


def _send_mcp_request(proc, method, params=None, req_id=1):
    """Send a JSON-RPC request and read the response."""
    request = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
    payload = json.dumps(request) + "\n"
    proc.stdin.write(payload)
    proc.stdin.flush()
    line = proc.stdout.readline()
    if not line:
        raise RuntimeError(f"No response for {method}")
    return json.loads(line)


def _send_mcp_notification(proc, method, params=None):
    """Send a JSON-RPC notification (no id)."""
    notification = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    proc.stdin.write(json.dumps(notification) + "\n")
    proc.stdin.flush()


def _init_index(project_root):
    """Initialize and index a project via CLI."""
    for cmd, timeout in [
        (["init", "--project-root", str(project_root)], 30),
        (["index", "--project-root", str(project_root)], 120),
    ]:
        result = subprocess.run(
            [_MEMORYGRAPH_BIN] + cmd,
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(f"{' '.join(cmd)} failed: {result.stderr}")


def _start_mcp(project_root):
    """Start the MCP server as a subprocess."""
    return subprocess.Popen(
        [_MEMORYGRAPH_BIN, "serve", "--mcp", "--project-root", str(project_root)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )


def _stop_mcp(proc, timeout=5):
    """Gracefully stop the MCP server subprocess."""
    if proc.poll() is not None:
        return
    proc.stdin.close()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


@pytest.mark.slow
class TestMCPE2E:
    """Real MCP server subprocess e2e tests."""

    def test_mcp_server_initialize_and_list_tools(self):
        """Start MCP server, initialize, and list available tools."""
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            project_root.mkdir()
            src_dir = project_root / "src"
            src_dir.mkdir()
            (src_dir / "app.py").write_text("""
def login(username: str, password: str) -> bool:
    '''Authenticate a user.'''
    if username == "admin":
        return True
    return False

def logout():
    '''End session.'''
    pass
""")

            _init_index(project_root)
            proc = _start_mcp(project_root)

            try:
                # Initialize MCP session
                resp = _send_mcp_request(proc, "initialize", params={
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0.0"},
                })
                assert "result" in resp, f"Init failed: {resp}"
                _send_mcp_notification(proc, "notifications/initialized")

                # List tools
                resp = _send_mcp_request(proc, "tools/list", req_id=2)
                tools = resp["result"].get("tools", [])
                tool_names = {t["name"] for t in tools}
                expected = {
                    "memorygraph_search", "memorygraph_callers", "memorygraph_callees",
                    "memorygraph_node", "memorygraph_context", "memorygraph_impact",
                    "memorygraph_diff", "memorygraph_semantic_context",
                    "memorygraph_annotations", "memorygraph_unknowns",
                    "memorygraph_insights", "memorygraph_semantic_search",
                }
                missing = expected - tool_names
                assert not missing, f"Missing tools: {missing}"

                # Call search
                resp = _send_mcp_request(proc, "tools/call", params={
                    "name": "memorygraph_search",
                    "arguments": {"query": "login", "limit": 5},
                }, req_id=3)
                content = resp["result"]["content"]
                data = json.loads(content[0]["text"])
                names = [r.get("qualified_name", r.get("name", "")) for r in data]
                assert any("login" in n for n in names), f"Names: {names}"

            finally:
                _stop_mcp(proc)

    def test_mcp_server_callers_callees(self):
        """Test callers/callees tools via MCP."""
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            project_root.mkdir()
            src_dir = project_root / "src"
            src_dir.mkdir()
            (src_dir / "mod.py").write_text("""
def helper():
    pass

def main():
    helper()
""")

            _init_index(project_root)
            proc = _start_mcp(project_root)

            try:
                _send_mcp_request(proc, "initialize", params={
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0.0"},
                })
                _send_mcp_notification(proc, "notifications/initialized")

                # callers: who calls helper?
                resp = _send_mcp_request(proc, "tools/call", params={
                    "name": "memorygraph_callers",
                    "arguments": {"symbol": "helper"},
                }, req_id=2)
                content = resp["result"]["content"]
                data = json.loads(content[0]["text"])
                sources = [r.get("source", "") for r in data]
                assert any("main" in s for s in sources), f"No 'main' in callers: {sources}"

                # callees: what does main call?
                resp = _send_mcp_request(proc, "tools/call", params={
                    "name": "memorygraph_callees",
                    "arguments": {"symbol": "main"},
                }, req_id=3)
                content = resp["result"]["content"]
                data = json.loads(content[0]["text"])
                targets = [r.get("target", "") for r in data]
                assert any("helper" in t for t in targets), f"No 'helper' in callees: {targets}"

            finally:
                _stop_mcp(proc)

    def test_mcp_semantic_annotation_roundtrip(self):
        """Full semantic annotation flow via MCP: add → verify → delete → verify."""
        from memorygraph.semantic.models import Annotation, SemanticDocument
        from memorygraph.semantic.store import SemanticStore

        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            project_root.mkdir()
            src_dir = project_root / "src"
            src_dir.mkdir()
            (src_dir / "app.py").write_text("""
def login(username: str) -> bool:
    '''Authenticate a user.'''
    return username == "admin"
""")

            _init_index(project_root)

            # Add annotation via SemanticStore (same path as web API handle_annotate)
            store = SemanticStore(str(project_root))
            doc = SemanticDocument(
                file="src/app.py",
                source="test",
                annotations=[Annotation(
                    symbol="login", kind="function",
                    summary="Auth entry point",
                    design_intent="Validate credentials",
                )],
            )
            store.save(doc)

            # Start MCP and verify annotation is visible
            proc = _start_mcp(project_root)

            try:
                resp = _send_mcp_request(proc, "initialize", params={
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0.0"},
                })
                assert "result" in resp, f"Init failed: {resp}"
                _send_mcp_notification(proc, "notifications/initialized")

                # Verify annotation appears via MCP
                resp = _send_mcp_request(proc, "tools/call", params={
                    "name": "memorygraph_annotations",
                    "arguments": {"symbol": "login", "file": "src/app.py"},
                }, req_id=2)
                content = resp["result"]["content"]
                data = json.loads(content[0]["text"])
                anns = data.get("annotations", [])
                assert len(anns) >= 1, f"Expected annotation, got: {data}"
                assert anns[0]["symbol"] == "login"
                assert anns[0]["summary"] == "Auth entry point"

                # Delete annotation via SemanticStore (same path as web API)
                result = store.delete_annotation("src/app.py", "login", index=0)
                assert result is True

                # Verify deletion via MCP
                resp = _send_mcp_request(proc, "tools/call", params={
                    "name": "memorygraph_annotations",
                    "arguments": {"symbol": "login", "file": "src/app.py"},
                }, req_id=3)
                content = resp["result"]["content"]
                data = json.loads(content[0]["text"])
                anns = data.get("annotations", [])
                login_anns = [a for a in anns if a.get("symbol") == "login"]
                assert len(login_anns) == 0, f"Annotation should be deleted, got: {login_anns}"

            finally:
                _stop_mcp(proc)
