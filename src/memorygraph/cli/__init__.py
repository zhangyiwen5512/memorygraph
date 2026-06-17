"""CLI commands for memorygraph.

Commands are organized by function group in commands/:
  indexing.py  — init, uninit, index, sync, watch
  querying.py  — query, context, files, affected, export, search-semantic, git-history, patterns
  serving.py   — serve, install
  semantic.py  — semantic-ingest, analyze, smells, metrics
  utils.py     — status, plugins, extract-from-conversation, hook
  doctor.py    — doctor

Shared utilities (cli/shared.py): _collect_files, _do_sync, _analyze_files, setup_logging.
"""
