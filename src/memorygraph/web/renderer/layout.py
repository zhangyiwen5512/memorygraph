"""Dashboard HTML structure — toolbar, three-column grid, modals, status bar."""
from __future__ import annotations


def toolbar_html() -> str:
    """Top toolbar with search, controls, and legend."""
    return """<div id="toolbar">
  <button id="btn-toggle-left" onclick="toggleLeftPanel()" title="Toggle file browser">☰</button>
  <div class="search-wrapper">
    <input id="search-input" type="text" placeholder="Search symbols... (Ctrl+K)" oninput="searchAsYouType()" onkeydown="searchKeyDown(event)">
    <div id="search-results"></div>
  </div>
  <div class="separator"></div>
  <select id="depth-select" onchange="reloadGraph()">
    <option value="1" selected>Depth 1</option>
    <option value="2">Depth 2</option>
    <option value="3">Depth 3</option>
    <option value="5">Depth 5</option>
  </select>
  <select id="layout-select" onchange="changeLayout()">
    <option value="force">Force-Directed</option>
    <option value="hierarchical">Hierarchical</option>
  </select>
  <button id="btn-fit" onclick="fitGraph()" title="Fit graph to view">⊞</button>
  <div class="separator"></div>
  <button id="btn-shortest-path" onclick="openShortestPathModal()" title="Find shortest path between two nodes">🔗 Path</button>
  <button id="btn-export" onclick="openExportModal()" title="Export graph">📥 Export</button>
  <button id="btn-tour" onclick="startTour('getting-started')" class="accent" title="Guided tour">🧭 Tour</button>
  <button id="btn-toggle-right" onclick="toggleRightPanel()" title="Toggle detail panel">☰</button>
  <div id="toolbar-spacer" style="flex:1"></div>
  <div id="legend"></div>
</div>"""


def main_layout_html() -> str:
    """Three-column grid: file browser | graph | detail panel."""
    return """<div id="main-area">
  <div id="left-panel">
    <div id="left-panel-content">
      <div class="panel-header">
        <h3>📁 Files</h3>
        <button class="panel-close" onclick="toggleLeftPanel()">×</button>
      </div>
      <input class="filter-input" id="file-filter" type="text" placeholder="Filter files..." oninput="filterFiles()">
      <div class="file-tree" id="file-tree"></div>
      <div id="stats-panel"></div>
    </div>
  </div>
  <div id="graph-container"></div>
  <div id="right-panel">
    <div id="right-panel-content">
      <div class="panel-header">
        <h3>🔍 Node Detail</h3>
        <button class="panel-close" onclick="toggleRightPanel()">×</button>
      </div>
      <div id="detail-content">
        <p class="detail-empty">Click a node in the graph to see details</p>
      </div>
    </div>
  </div>
</div>"""


def status_bar_html() -> str:
    """Bottom status bar."""
    return """<div id="status-bar">
  <span id="status-left">Ready — type to search or click a node to explore</span>
  <span class="kb-hint" id="status-right">/ search · Esc close · +/− zoom · R reset</span>
</div>"""


def export_modal_html() -> str:
    """Export format selection modal."""
    return """<div class="modal-backdrop" id="export-modal">
  <div class="modal">
    <h2>📥 Export Graph</h2>
    <label><input type="radio" name="export-fmt" value="png" checked> PNG Image</label>
    <label><input type="radio" name="export-fmt" value="svg"> SVG Vector</label>
    <label><input type="radio" name="export-fmt" value="json"> JSON (full graph data)</label>
    <div style="margin-top:12px; display:flex; justify-content:flex-end;">
      <button class="btn-cancel" onclick="closeExportModal()">Cancel</button>
      <button class="btn-primary" onclick="doExport()">Download</button>
    </div>
  </div>
</div>"""


def shortest_path_modal_html() -> str:
    """Shortest path finder modal."""
    return """<div class="modal-backdrop" id="shortest-path-modal">
  <div class="modal">
    <h2>🔗 Find Shortest Path</h2>
    <label for="sp-source">Source Symbol</label>
    <input id="sp-source" type="text" placeholder="e.g. login_handler" oninput="searchPathNode('source')">
    <div id="sp-source-results" class="path-search-results" style="max-height:120px;overflow-y:auto;"></div>
    <label for="sp-target">Target Symbol</label>
    <input id="sp-target" type="text" placeholder="e.g. query_db" oninput="searchPathNode('target')">
    <div id="sp-target-results" class="path-search-results" style="max-height:120px;overflow-y:auto;"></div>
    <div id="sp-result" style="margin-top:10px;font-size:12px;"></div>
    <div style="margin-top:12px; display:flex; justify-content:flex-end; gap:6px;">
      <button class="btn-cancel" onclick="closeShortestPathModal()">Close</button>
      <button class="btn-danger" onclick="clearShortestPath()">Clear</button>
      <button class="btn-primary" onclick="findShortestPath()">Find Path</button>
    </div>
  </div>
</div>"""


def tour_overlay_html() -> str:
    """Guided tour overlay container."""
    return """<div id="tour-backdrop"></div>
<div class="tour-card" id="tour-card" style="display:none;">
  <h3 id="tour-title"></h3>
  <p id="tour-content"></p>
  <div class="tour-nav">
    <span class="tour-progress" id="tour-progress"></span>
    <div>
      <button onclick="tourPrev()" id="tour-prev-btn">← Prev</button>
      <button onclick="tourNext()" id="tour-next-btn">Next →</button>
      <button onclick="tourSkip()" id="tour-skip-btn">Skip</button>
    </div>
  </div>
</div>"""


def toast_html() -> str:
    """Toast notification container."""
    return """<div id="toast"><span class="toast-msg"></span><span class="toast-close" onclick="hideToast()">×</span></div>"""


def all_layout_html() -> str:
    """Return complete body HTML structure (all panels + modals)."""
    return (
        toolbar_html()
        + main_layout_html()
        + status_bar_html()
        + export_modal_html()
        + shortest_path_modal_html()
        + tour_overlay_html()
        + toast_html()
    )
