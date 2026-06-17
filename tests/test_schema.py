"""Tests for schema module."""
import os
import sqlite3
import tempfile

import pytest

from memorygraph.storage.schema import SYMBOL_KIND_TO_TABLE, SYMBOL_TABLES, init_db


def test_symbol_tables_list():
    """验证 6 张符号表在常量中。"""
    assert "functions" in SYMBOL_TABLES
    assert "methods" in SYMBOL_TABLES
    assert "classes" in SYMBOL_TABLES
    assert "interfaces" in SYMBOL_TABLES
    assert "type_aliases" in SYMBOL_TABLES
    assert "variables" in SYMBOL_TABLES
    assert len(SYMBOL_TABLES) == 6


def test_symbol_kind_to_table_mapping():
    assert SYMBOL_KIND_TO_TABLE["function"] == "functions"
    assert SYMBOL_KIND_TO_TABLE["method"] == "methods"
    assert SYMBOL_KIND_TO_TABLE["class"] == "classes"
    assert SYMBOL_KIND_TO_TABLE["interface"] == "interfaces"
    assert SYMBOL_KIND_TO_TABLE["type"] == "type_aliases"
    assert SYMBOL_KIND_TO_TABLE["variable"] == "variables"


def test_init_db_creates_all_tables():
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test.db")
    try:
        conn = sqlite3.connect(db_path)
        init_db(conn)

        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = {t[0] for t in tables}

        expected = {
            "files", "functions", "methods", "classes",
            "interfaces", "type_aliases", "variables",
            "edges", "fts_index"
        }
        for name in expected:
            assert name in table_names, f"Table {name} not created"
        conn.close()
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_init_db_idempotent():
    """重复执行 init_db 不报错。"""
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test.db")
    try:
        conn = sqlite3.connect(db_path)
        init_db(conn)
        init_db(conn)
        init_db(conn)
        conn.close()
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_edges_table_has_correct_columns():
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test.db")
    try:
        conn = sqlite3.connect(db_path)
        init_db(conn)
        info = conn.execute("PRAGMA table_info(edges)").fetchall()
        col_names = [row[1] for row in info]
        assert "source" in col_names
        assert "target" in col_names
        assert "kind" in col_names
        assert "source_file_id" in col_names
        assert "target_file_id" in col_names
        assert "source_start_line" in col_names
        assert "source_start_col" in col_names
        conn.close()
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_files_table_has_file_hash():
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test.db")
    try:
        conn = sqlite3.connect(db_path)
        init_db(conn)
        info = conn.execute("PRAGMA table_info(files)").fetchall()
        col_names = [row[1] for row in info]
        assert "file_hash" in col_names
        conn.close()
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_validate_table_name_valid():
    """validate_table_name should return the name for valid table names."""
    from memorygraph.storage.schema import validate_table_name
    for name in SYMBOL_TABLES:
        assert validate_table_name(name) == name


def test_validate_table_name_invalid():
    """validate_table_name should raise ValueError for invalid table names."""
    import pytest

    from memorygraph.storage.schema import validate_table_name
    with pytest.raises(ValueError, match="not in the allowed set"):
        validate_table_name("malicious; DROP TABLE files;")


class TestValidateTableNameParametrized:
    """Parameterized edge cases for validate_table_name."""

    @pytest.mark.parametrize("table_name,should_pass", [
        ("functions", True),
        ("methods", True),
        ("classes", True),
        ("interfaces", True),
        ("type_aliases", True),
        ("variables", True),
        ("malicious; DROP TABLE files;", False),
        ("users", False),
        ("__init__", False),
        ("", False),
        ("../etc/passwd", False),
        ("edges", False),
        ("fts_index", False),
    ])
    def test_validate_table_name(self, table_name, should_pass):
        import pytest

        from memorygraph.storage.schema import validate_table_name
        if should_pass:
            assert validate_table_name(table_name) == table_name
        else:
            with pytest.raises(ValueError):
                validate_table_name(table_name)


def test_apply_migrations_applies_pending():
    """_apply_migrations should apply migrations with version > current."""
    import os
    import sqlite3
    import tempfile

    from memorygraph.storage.schema import MIGRATIONS

    # Add a test migration, run it, then clean up
    test_migration = (999, "test_add_column", "ALTER TABLE files ADD COLUMN test_col TEXT DEFAULT '';")
    try:
        MIGRATIONS.append(test_migration)

        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")
        try:
            conn = sqlite3.connect(db_path)
            from memorygraph.storage.schema import init_db
            init_db(conn)

            # Verify the migration was applied
            cur = conn.execute("SELECT version FROM schema_version WHERE version=999")
            assert cur.fetchone() is not None

            # Verify the DDL was applied
            info = conn.execute("PRAGMA table_info(files)").fetchall()
            col_names = [row[1] for row in info]
            assert "test_col" in col_names

            conn.close()
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
    finally:
        MIGRATIONS.remove(test_migration)


def test_apply_migrations_skips_applied():
    """_apply_migrations should skip migrations already applied."""
    import os
    import sqlite3
    import tempfile

    from memorygraph.storage.schema import MIGRATIONS, _apply_migrations

    test_migration = (998, "test_skip", "ALTER TABLE files ADD COLUMN skip_col TEXT DEFAULT '';")
    try:
        MIGRATIONS.append(test_migration)

        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")
        try:
            conn = sqlite3.connect(db_path)
            from memorygraph.storage.schema import init_db

            # Initialize then apply migration once
            init_db(conn)
            # Second call should skip because migration already applied
            _apply_migrations(conn)

            # Verify migration exists but wasn't double-applied
            cur = conn.execute("SELECT COUNT(*) FROM schema_version WHERE version=998")
            assert cur.fetchone()[0] == 1

            conn.close()
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
    finally:
        MIGRATIONS.remove(test_migration)
