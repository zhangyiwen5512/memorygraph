"""Doctor command — health checks for memorygraph installation."""
import logging
from pathlib import Path

import click

logger = logging.getLogger(__name__)


@click.command()
@click.option("--project-root", default=".", help="Project root directory")
@click.option("--json", "as_json", is_flag=True, default=False,
              help="Output as JSON (machine-readable)")
def doctor(project_root: str, as_json: bool = False):
    """Check memorygraph health and report issues.

    Verifies: database integrity, dependency availability,
    file consistency, semantic coverage, embedding status.
    """
    import json as _json

    root = Path(project_root).resolve()
    mg_dir = root / ".memorygraph"
    db_path = mg_dir / "memorygraph.db"

    issues: list[str] = []
    ok: list[str] = []
    json_data: dict = {"status": "unknown", "checks": [], "issues": []}

    # 1. Project initialization
    if not mg_dir.exists():
        if as_json:
            click.echo(_json.dumps({
                "status": "not_initialized",
                "hint": "Run: memorygraph init",
            }))
            return
        click.echo("❌ Not initialized — run: memorygraph init")
        return
    ok.append("Project initialized")
    json_data["checks"].append({"name": "initialized", "status": "ok"})

    # 2. Database existence
    db_size_mb = 0.0
    if db_path.exists():
        db_size_mb = db_path.stat().st_size / (1024 * 1024)
        ok.append(f"Database: {db_size_mb:.1f}MB")
        json_data["checks"].append({
            "name": "database", "status": "ok", "size_mb": round(db_size_mb, 1),
        })
    else:
        issues.append("Database missing — run: memorygraph index")
        json_data["issues"].append("database_missing")

    # 3. Database integrity + Embeddings
    emb_count = 0
    db_stats: dict = {}
    try:
        from memorygraph.storage import create_storage_manager
        mgr = create_storage_manager(project_root)
        mgr.initialize()
        try:
            db_stats = mgr.stats()
            ok.append(f"Files indexed: {db_stats['file_count']}")
            ok.append(f"Symbols: {db_stats['symbol_count']}")
            ok.append(f"Edges: {db_stats['edge_count']}")
            for key, label in [("file_count", "files_indexed"),
                               ("symbol_count", "symbols"),
                               ("edge_count", "edges")]:
                json_data["checks"].append({
                    "name": label, "status": "ok",
                    "count": db_stats.get(key, 0),
                })
            if db_stats.get("file_count", 0) == 0:
                issues.append("No files indexed — run: memorygraph index")
                json_data["issues"].append("no_files_indexed")
        except Exception as e:
            issues.append(f"Database error: {e}")
            json_data["issues"].append(f"db_error: {e}")

        # Embeddings count
        try:
            conn = mgr.get_conn()
            emb_count = conn.execute(
                "SELECT COUNT(*) FROM embeddings"
            ).fetchone()[0]
        except Exception:
            logger.debug("Embeddings check failed, assuming 0", exc_info=True)
        mgr.close()
    except Exception as e:
        issues.append(f"Database error: {e}")
        json_data["issues"].append(f"db_error: {e}")

    if emb_count > 0:
        ok.append(f"Embeddings: {emb_count} vectors")
        json_data["checks"].append({
            "name": "embeddings", "status": "ok", "count": emb_count,
        })
    else:
        ok.append("Embeddings: none (run: memorygraph index --embed)")
        json_data["checks"].append({"name": "embeddings", "status": "unavailable"})

    # 4. Dependencies
    deps: dict = {}
    for mod, label in [("radon", "radon"), ("psycopg2", "psycopg2")]:
        try:
            __import__(mod)
            ok.append(f"{label}: available")
            deps[label] = True
        except ImportError:
            if mod == "psycopg2":
                ok.append(f"{label}: not installed (SQLite only)")
            else:
                issues.append(f"{label} not installed — pip install {label}")
            deps[label] = False

    try:
        from sentence_transformers import SentenceTransformer  # noqa: F401
        ok.append("sentence-transformers: available")
        deps["sentence_transformers"] = True
    except ImportError:
        ok.append("sentence-transformers: not installed")
        deps["sentence_transformers"] = False
    json_data["checks"].append({
        "name": "dependencies", "status": "ok", "details": deps,
    })

    # 5. Semantic documents
    sem_dir = mg_dir / "semantic"
    sem_count = 0
    if sem_dir.exists():
        sem_count = len(list(sem_dir.glob("*.json")))
        ok.append(f"Semantic docs: {sem_count} files")
    else:
        ok.append("Semantic docs: none")
    json_data["checks"].append({
        "name": "semantic_docs", "status": "ok", "count": sem_count,
    })

    # 6. Backend
    from memorygraph.storage.backend import detect_backend
    backend = detect_backend(project_root)
    ok.append(f"Backend: {backend}")
    json_data["checks"].append({
        "name": "backend", "status": "ok", "value": backend,
    })

    json_data["status"] = "healthy" if not issues else "degraded"

    if as_json:
        click.echo(_json.dumps(json_data, indent=2, default=str))
        return

    click.echo("\n=== memorygraph doctor ===\n")
    for item in ok:
        click.echo(f"  ✅ {item}")
    if issues:
        click.echo("")
        for item in issues:
            click.echo(f"  ❌ {item}")
    else:
        click.echo("\n  All checks passed!")
    click.echo("")


def register(cli) -> None:
    cli.add_command(doctor)
