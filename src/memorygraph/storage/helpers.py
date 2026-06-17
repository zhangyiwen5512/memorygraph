"""Shared storage helpers used by both SQLite and PostgreSQL backends."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from memorygraph.parsing.ir import Symbol


def qualified_name(sym: Symbol) -> str:
    """Return the fully qualified name for *sym*."""
    if sym.parent_symbol:
        return f"{sym.parent_symbol}.{sym.name}"
    return sym.name


def symbol_to_row(sym: Symbol, qn: str, *, fid: int | None = None) -> tuple:
    """Convert a Symbol to a database insert row tuple."""
    from memorygraph.parsing.ir import SymbolKind

    span = sym.span
    is_partial = int(sym.is_partial)
    prefix = (fid,) if fid is not None else ()

    if sym.kind == SymbolKind.METHOD:
        return prefix + (
            sym.name, qn, sym.parent_symbol or "",
            sym.signature or "",
            span.start_line, span.start_col,
            span.end_line, span.end_col, is_partial,
        )
    elif sym.kind == SymbolKind.FUNCTION:
        return prefix + (
            sym.name, qn, sym.signature or "",
            span.start_line, span.start_col,
            span.end_line, span.end_col, is_partial,
        )
    else:
        return prefix + (
            sym.name, qn,
            span.start_line, span.start_col,
            span.end_line, span.end_col, is_partial,
        )


