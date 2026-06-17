"""Dashboard CSS — dark theme, three-column grid layout."""
from __future__ import annotations


def all_css() -> str:
    """Return complete <style> block for the dashboard."""
    return """<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; background: #0d1117; color: #c9d1d9; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }

/* ── Toolbar ── */
#toolbar { padding: 8px 12px; background: #161b22; display: flex; gap: 8px; align-items: center; border-bottom: 1px solid #21262d; flex-wrap: wrap; min-height: 44px; z-index: 10; }
#toolbar input, #toolbar select, #toolbar button { padding: 5px 10px; border-radius: 6px; border: 1px solid #30363d; background: #0d1117; color: #c9d1d9; font-size: 13px; }
#toolbar button { cursor: pointer; background: #21262d; }
#toolbar button:hover { background: #30363d; }
#toolbar button.active { background: #1f6feb; border-color: #1f6feb; }
#toolbar button.accent { background: #238636; border-color: #238636; }
#toolbar button.accent:hover { background: #2ea043; }
.search-wrapper { position: relative; flex: 1; max-width: 400px; }
.search-wrapper input { width: 100%; padding-right: 30px; }
#search-results { position: absolute; top: 100%; left: 0; right: 0; background: #161b22; border: 1px solid #30363d; max-height: 300px; overflow-y: auto; z-index: 100; display: none; border-radius: 6px; margin-top: 2px; }
#search-results.show { display: block; }
#search-results div { padding: 8px 12px; cursor: pointer; font-size: 12px; border-bottom: 1px solid #21262d; display: flex; justify-content: space-between; align-items: center; }
#search-results div:hover, #search-results div.focused { background: #1f6feb22; }
#search-results .kind-badge { font-size: 10px; padding: 2px 6px; border-radius: 10px; background: #21262d; color: #8b949e; }
.separator { width: 1px; height: 24px; background: #30363d; margin: 0 4px; }

/* ── Main layout ── */
#main-area { display: flex; flex: 1; min-height: 0; }
#left-panel { width: 260px; background: #161b22; border-right: 1px solid #21262d; display: flex; flex-direction: column; transition: width 0.2s, padding 0.2s; overflow: hidden; }
#left-panel.collapsed { width: 0; padding: 0; border: none; }
#left-panel-content { padding: 12px; overflow-y: auto; flex: 1; }
#graph-container { flex: 1; min-width: 0; position: relative; }
#right-panel { width: 360px; background: #161b22; border-left: 1px solid #21262d; display: flex; flex-direction: column; transition: width 0.2s, padding 0.2s; overflow: hidden; }
#right-panel.collapsed { width: 0; padding: 0; border: none; }
#right-panel-content { padding: 12px; overflow-y: auto; flex: 1; }
.panel-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px solid #21262d; }
.panel-header h3 { font-size: 13px; font-weight: 600; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; }
.panel-close { background: none; border: none; color: #8b949e; cursor: pointer; font-size: 16px; padding: 2px 6px; }
.panel-close:hover { color: #f85149; }

/* ── File browser ── */
.file-tree { font-size: 12px; }
.file-tree .dir { color: #58a6ff; cursor: pointer; padding: 2px 0; user-select: none; }
.file-tree .dir:hover { color: #79c0ff; }
.file-tree .dir::before { content: '▸ '; display: inline-block; width: 14px; font-size: 10px; }
.file-tree .dir.open::before { content: '▾ '; }
.file-tree .dir-children { display: none; padding-left: 14px; }
.file-tree .dir-children.open { display: block; }
.file-tree .file { color: #c9d1d9; cursor: pointer; padding: 2px 4px; border-radius: 3px; display: flex; justify-content: space-between; }
.file-tree .file:hover { background: #1f6feb22; }
.file-tree .file .sym-count { color: #484f58; font-size: 10px; }
.file-tree .filter-input { width: 100%; padding: 4px 8px; border-radius: 4px; border: 1px solid #30363d; background: #0d1117; color: #c9d1d9; font-size: 11px; margin-bottom: 8px; }

/* ── Stats ── */
.stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-top: 12px; }
.stat-card { background: #0d1117; border-radius: 6px; padding: 8px; text-align: center; border: 1px solid #21262d; }
.stat-card .value { font-size: 18px; font-weight: 700; color: #58a6ff; }
.stat-card .label { font-size: 10px; color: #8b949e; text-transform: uppercase; margin-top: 2px; }

/* ── Detail panel ── */
.detail-section { margin-bottom: 14px; }
.detail-section h4 { font-size: 11px; color: #8b949e; text-transform: uppercase; margin-bottom: 4px; padding-bottom: 2px; border-bottom: 1px solid #21262d; }
.detail-section .detail-value { font-size: 12px; color: #c9d1d9; word-break: break-all; }
.detail-section .detail-value.code { font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', monospace; font-size: 11px; background: #0d1117; padding: 6px 8px; border-radius: 4px; }
.detail-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 10px; margin: 1px; }
.badge-kind { background: #1f6feb22; color: #58a6ff; }
.badge-role { background: #23863622; color: #3fb950; }
.badge-layer { background: #d2992222; color: #d29922; }
.detail-callers, .detail-callees { font-size: 11px; }
.detail-callers a, .detail-callees a { color: #58a6ff; cursor: pointer; text-decoration: none; }
.detail-callers a:hover, .detail-callees a:hover { text-decoration: underline; }
.detail-empty { color: #484f58; font-size: 11px; font-style: italic; }

/* ── Graph legend ── */
#legend { display: flex; gap: 12px; align-items: center; margin-left: auto; flex-wrap: wrap; }
.legend-group { display: flex; gap: 6px; align-items: center; }
.legend-item { display: flex; align-items: center; gap: 3px; font-size: 10px; color: #8b949e; }
.legend-dot { width: 10px; height: 10px; border-radius: 50%; }
.legend-square { width: 10px; height: 10px; border-radius: 2px; }

/* ── Modals ── */
.modal-backdrop { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.6); z-index: 200; justify-content: center; align-items: center; }
.modal-backdrop.open { display: flex; }
.modal { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; max-width: 500px; width: 90%; max-height: 80vh; overflow-y: auto; }
.modal h2 { font-size: 16px; margin-bottom: 12px; color: #58a6ff; }
.modal h3 { font-size: 13px; margin: 10px 0 6px; color: #c9d1d9; }
.modal label { font-size: 12px; color: #8b949e; display: block; margin-top: 8px; }
.modal input, .modal select { width: 100%; padding: 6px 8px; border-radius: 4px; border: 1px solid #30363d; background: #0d1117; color: #c9d1d9; font-size: 12px; }
.modal button { padding: 6px 14px; border-radius: 6px; border: 1px solid #30363d; cursor: pointer; font-size: 12px; margin-right: 6px; margin-top: 10px; }
.modal .btn-primary { background: #1f6feb; border-color: #1f6feb; color: #fff; }
.modal .btn-primary:hover { background: #388bfd; }
.modal .btn-cancel { background: #21262d; color: #c9d1d9; }
.modal .btn-cancel:hover { background: #30363d; }
.modal .btn-danger { background: #da3633; border-color: #da3633; color: #fff; }

/* ── Tour overlay ── */
#tour-backdrop { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 300; }
#tour-backdrop.open { display: block; }
.tour-card { position: fixed; z-index: 301; background: #161b22; border: 2px solid #1f6feb; border-radius: 8px; padding: 16px; max-width: 360px; box-shadow: 0 8px 24px rgba(0,0,0,0.5); }
.tour-card::after { content: ''; position: absolute; width: 12px; height: 12px; background: #161b22; border: 2px solid #1f6feb; transform: rotate(45deg); }
.tour-card.bottom::after { top: -8px; left: 20px; border-right: none; border-bottom: none; }
.tour-card.top::after { bottom: -8px; left: 20px; border-left: none; border-top: none; }
.tour-card h3 { font-size: 14px; color: #58a6ff; margin-bottom: 8px; }
.tour-card p { font-size: 12px; color: #c9d1d9; margin-bottom: 12px; line-height: 1.5; }
.tour-card .tour-nav { display: flex; justify-content: space-between; align-items: center; }
.tour-card button { padding: 4px 12px; border-radius: 4px; border: 1px solid #30363d; background: #21262d; color: #c9d1d9; cursor: pointer; font-size: 11px; }
.tour-card .tour-progress { font-size: 11px; color: #8b949e; }

/* ── Notification toast ── */
#toast { position: fixed; bottom: 40px; right: 20px; background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 10px 16px; font-size: 12px; z-index: 400; display: none; max-width: 350px; }
#toast.show { display: block; }
#toast.error { border-color: #f85149; }
#toast.success { border-color: #3fb950; }
#toast .toast-msg { margin-right: 20px; }
#toast .toast-close { position: absolute; right: 6px; top: 6px; cursor: pointer; color: #8b949e; font-size: 14px; }

/* ── Status bar ── */
#status-bar { padding: 6px 12px; background: #161b22; font-size: 11px; color: #484f58; border-top: 1px solid #21262d; display: flex; justify-content: space-between; }
#status-bar .kb-hint { color: #30363d; }

/* ── Responsive ── */
@media (max-width: 900px) {
  #left-panel { width: 0; padding: 0; } #right-panel { width: 0; padding: 0; }
}
</style>"""
