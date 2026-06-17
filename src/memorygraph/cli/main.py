"""CLI entry point — memorygraph 命令行工具。

Commands are organized by function group in commands/:
  indexing.py  — init, uninit, index, sync, watch
  querying.py  — query, context, files, affected, export, search-semantic
  serving.py   — serve, install
  semantic.py  — semantic-ingest, analyze, smells, metrics
  utils.py     — status, plugins, extract-from-conversation
  doctor.py    — doctor
"""
import click

from memorygraph import __version__


@click.group()
@click.version_option(version=__version__)
def cli():
    """memorygraph — local code knowledge graph tool."""
    pass


# Register all command modules
from memorygraph.cli.commands import doctor, indexing, querying, semantic, serving, utils

indexing.register(cli)
querying.register(cli)
serving.register(cli)
semantic.register(cli)
utils.register(cli)
doctor.register(cli)


if __name__ == "__main__":
    cli()
