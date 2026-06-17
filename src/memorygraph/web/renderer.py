"""Backward-compatibility shim — re-exports from renderer/ package.

When both ``renderer.py`` and ``renderer/`` exist in the same directory,
Python's import system resolves the *package* (``renderer/__init__.py``)
rather than this module.  This file is kept for documentation and to
prevent import errors in environments that may have cached the old
module path.

Code should import ``render_html`` (or ``render_dashboard``) from
``memorygraph.web.renderer`` (the package).
"""
from __future__ import annotations

# All actual rendering logic lives in renderer/__init__.py.
# The package's __init__.py exports both render_dashboard and the
# backward-compatible alias render_html.
