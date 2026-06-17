"""Tests for LSIF exporter."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile

from memorygraph.export import export_lsif
from memorygraph.export.lsif import _map_language


def _setup_test_db(db_path: str) -> None:
    """Create a test database with known symbols and edges."""
    from memorygraph.storage.schema import init_db

    conn = sqlite3.connect(db_path)
    init_db(conn)

    # Insert files
    conn.executemany(
        "INSERT INTO files (path, language, file_hash, symbol_count, edge_count) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            ("/project/main.py", "python", "hash1", 3, 2),
            ("/project/utils.py", "python", "hash2", 2, 1),
        ],
    )
    conn.commit()

    # Get file IDs
    (fid1,) = conn.execute("SELECT id FROM files WHERE path = '/project/main.py'").fetchone()
    (fid2,) = conn.execute("SELECT id FROM files WHERE path = '/project/utils.py'").fetchone()

    # Insert functions
    conn.executemany(
        "INSERT INTO functions (file_id, name, qualified_name, signature, "
        "start_line, start_col, end_line, end_col, is_partial) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (fid1, "main", "main", "def main():", 10, 0, 15, 0, 0),
            (fid2, "helper", "helper", "def helper(x):", 5, 0, 8, 0, 0),
        ],
    )
    # Insert a class
    conn.executemany(
        "INSERT INTO classes (file_id, name, qualified_name, "
        "start_line, start_col, end_line, end_col, is_partial) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (fid1, "MyClass", "MyClass", 20, 0, 30, 0, 0),
        ],
    )
    # Insert a method
    conn.executemany(
        "INSERT INTO methods (file_id, name, qualified_name, parent_class, signature, "
        "start_line, start_col, end_line, end_col, is_partial) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (fid1, "method1", "MyClass.method1", "MyClass",
             "def method1(self):", 22, 4, 25, 4, 0),
        ],
    )

    # Insert edges (calls)
    conn.executemany(
        "INSERT INTO edges (source, target, kind, source_file_id, "
        "source_start_line, source_start_col, source_end_line, source_end_col, "
        "target_file_id, target_start_line, target_start_col, target_end_line, target_end_col) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("main", "helper", "calls", fid1, 12, 4, 12, 10,
             fid2, None, None, None, None),
            ("MyClass.method1", "main", "calls", fid1, 23, 8, 23, 12,
             fid1, None, None, None, None),
        ],
    )
    conn.commit()
    conn.close()


class TestLSIFExport:
    def test_export_basic(self):
        """Export a test DB and verify LSIF structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            output_path = os.path.join(tmpdir, "output.lsif")

            _setup_test_db(db_path)
            line_count = export_lsif(db_path, output_path, project_root="/project")

            assert line_count > 0
            assert os.path.exists(output_path)

            # Parse JSON lines
            with open(output_path) as f:
                lines = [json.loads(line) for line in f if line.strip()]

            assert len(lines) == line_count

            # Must have metaData and project vertices
            vertices_by_label: dict[str, list[dict]] = {}
            for obj in lines:
                if obj["type"] == "vertex":
                    vertices_by_label.setdefault(obj["label"], []).append(obj)

            assert "metaData" in vertices_by_label
            assert "project" in vertices_by_label
            assert "document" in vertices_by_label
            assert len(vertices_by_label["document"]) == 2  # 2 test files

            # Must have range vertices for symbols
            assert "range" in vertices_by_label
            # 4 symbols + 2 edge reference locations = 6 ranges
            assert len(vertices_by_label["range"]) == 6

            # Must have hoverResult for each symbol
            assert "hoverResult" in vertices_by_label
            assert len(vertices_by_label["hoverResult"]) == 4

            # Must have definitionResult for each symbol
            assert "definitionResult" in vertices_by_label
            assert len(vertices_by_label["definitionResult"]) == 4

    def test_export_empty_db(self):
        """Export an empty database (no symbols). Should not crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            output_path = os.path.join(tmpdir, "output.lsif")

            from memorygraph.storage.schema import init_db
            conn = sqlite3.connect(db_path)
            init_db(conn)
            conn.close()

            line_count = export_lsif(db_path, output_path, project_root="/project")
            assert line_count >= 2  # metaData + project at minimum

            with open(output_path) as f:
                lines = [json.loads(line) for line in f if line.strip()]

            vertices_by_label: dict[str, list[dict]] = {}
            for obj in lines:
                if obj["type"] == "vertex":
                    vertices_by_label.setdefault(obj["label"], []).append(obj)

            assert "metaData" in vertices_by_label
            assert "project" in vertices_by_label

    def test_export_output_is_valid_json_lines(self):
        """Every line in the LSIF output must be valid JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            output_path = os.path.join(tmpdir, "output.lsif")

            _setup_test_db(db_path)
            export_lsif(db_path, output_path, project_root="/project")

            with open(output_path) as f:
                for i, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    assert "id" in obj, f"Line {i}: missing 'id'"
                    assert "type" in obj, f"Line {i}: missing 'type'"
                    assert obj["type"] in ("vertex", "edge"), \
                        f"Line {i}: bad type {obj['type']}"
                    if obj["type"] == "vertex":
                        assert "label" in obj, f"Line {i}: vertex missing 'label'"
                    if obj["type"] == "edge":
                        assert "label" in obj, f"Line {i}: edge missing 'label'"
                        assert "outV" in obj, f"Line {i}: edge missing 'outV'"
                        assert "inV" in obj, f"Line {i}: edge missing 'inV'"

    def test_export_ids_are_unique_and_monotonic(self):
        """All LSIF IDs should be unique and increasing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            output_path = os.path.join(tmpdir, "output.lsif")

            _setup_test_db(db_path)
            export_lsif(db_path, output_path, project_root="/project")

            with open(output_path) as f:
                ids = [
                    json.loads(line)["id"]
                    for line in f if line.strip()
                ]

            assert len(ids) == len(set(ids)), "IDs are not unique"
            assert ids == sorted(ids), "IDs are not monotonic"

    def test_export_document_uris(self):
        """Document vertices must have correct file:// URIs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            output_path = os.path.join(tmpdir, "output.lsif")

            _setup_test_db(db_path)
            export_lsif(db_path, output_path, project_root="/project")

            with open(output_path) as f:
                docs = [
                    json.loads(line)
                    for line in f if line.strip()
                    if json.loads(line).get("label") == "document"
                ]

            uris = {d["uri"] for d in docs}
            assert "file:///project/main.py" in uris
            assert "file:///project/utils.py" in uris

    def test_map_language(self):
        """Test language mapping normalization."""
        assert _map_language("python") == "python"
        assert _map_language("typescript") == "typescript"
        assert _map_language("JavaScript") == "javascript"
        assert _map_language("GO") == "go"
        assert _map_language("csharp") == "csharp"
        assert _map_language("kotlin") == "kotlin"  # pass through

    def test_export_with_missing_file_reference(self):
        """Edge referencing a file not in files table should be skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            output_path = os.path.join(tmpdir, "output.lsif")

            from memorygraph.storage.schema import init_db
            conn = sqlite3.connect(db_path)
            init_db(conn)

            # Insert one file
            conn.execute(
                "INSERT INTO files (path, language, file_hash, symbol_count, edge_count) "
                "VALUES (?, ?, ?, ?, ?)",
                ("/project/main.py", "python", "hash1", 1, 1),
            )
            conn.commit()
            fid = conn.execute("SELECT id FROM files WHERE path = '/project/main.py'").fetchone()[0]

            # Insert a function in that file
            conn.execute(
                "INSERT INTO functions (file_id, name, qualified_name, signature, "
                "start_line, start_col, end_line, end_col, is_partial) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (fid, "func", "func", "def func():", 1, 0, 1, 10, 0),
            )

            # Insert edge referencing a non-existent file (file_id 999)
            conn.execute(
                "INSERT INTO edges (source, target, kind, source_file_id, "
                "source_start_line, source_start_col, source_end_line, source_end_col, "
                "target_file_id, target_start_line, target_start_col, target_end_line, target_end_col) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("func", "missing_func", "calls", 999, 1, 4, 1, 10,
                 None, None, None, None, None),
            )
            conn.commit()
            conn.close()

            line_count = export_lsif(db_path, output_path, project_root="/project")
            assert line_count > 0  # Should not crash

            # Verify output is valid
            with open(output_path) as f:
                for line in f:
                    if line.strip():
                        json.loads(line)  # Must parse

    def test_export_symbol_with_orphan_file_id_skipped(self):
        """Symbol referencing a file not in files table should be skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            output_path = os.path.join(tmpdir, "output.lsif")

            from memorygraph.storage.schema import init_db
            conn = sqlite3.connect(db_path)
            init_db(conn)

            # Insert one file
            conn.execute(
                "INSERT INTO files (path, language, file_hash, symbol_count, edge_count) "
                "VALUES (?, ?, ?, ?, ?)",
                ("/project/main.py", "python", "hash1", 0, 0),
            )
            conn.commit()

            # Insert a function with a non-existent file_id (999)
            conn.execute(
                "INSERT INTO functions (file_id, name, qualified_name, signature, "
                "start_line, start_col, end_line, end_col, is_partial) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (999, "orphan", "orphan", "def orphan():", 1, 0, 1, 10, 0),
            )
            conn.commit()
            conn.close()

            line_count = export_lsif(db_path, output_path, project_root="/project")
            assert line_count > 0  # Should not crash — orphan skipped via continue

            with open(output_path) as f:
                lines = [json.loads(line) for line in f if line.strip()]

            # No range vertex for the orphan symbol
            ranges = [l for l in lines if l.get("label") == "range"]
            assert len(ranges) == 0  # Orphan symbol was skipped
