"""Dashboard renderer — assemble all HTML/JS/CSS fragments into a complete page."""
from __future__ import annotations

from memorygraph.web.renderer.export import export_js  # noqa: F401
from memorygraph.web.renderer.graph_viz import graph_init_js  # noqa: F401
from memorygraph.web.renderer.layout import all_layout_html  # noqa: F401
from memorygraph.web.renderer.panels import panels_js  # noqa: F401
from memorygraph.web.renderer.search import search_js  # noqa: F401
from memorygraph.web.renderer.styles import all_css  # noqa: F401
from memorygraph.web.renderer.tours import tour_js, tours_data_json  # noqa: F401

__all__ = ["render_dashboard", "render_html"]


def _toast_js() -> str:
    """Toast notification helper JS."""
    return """<script>
function showToast(msg, isError) {
  var t = document.getElementById('toast');
  t.querySelector('.toast-msg').textContent = msg;
  t.className = isError ? 'show error' : 'show success';
  clearTimeout(t._timeout);
  t._timeout = setTimeout(function() { t.classList.remove('show','error','success'); }, 4000);
}
function hideToast() {
  var t = document.getElementById('toast');
  t.classList.remove('show','error','success');
}
</script>"""


def _shortest_path_js() -> str:
    """Shortest path finder JS."""
    return """<script>
var spSearchTimers = {source: null, target: null};

function openShortestPathModal() {
  document.getElementById('shortest-path-modal').classList.add('open');
}

function closeShortestPathModal() {
  document.getElementById('shortest-path-modal').classList.remove('open');
}

function searchPathNode(which) {
  clearTimeout(spSearchTimers[which]);
  var q = document.getElementById('sp-' + which).value.trim();
  var resultsEl = document.getElementById('sp-' + which + '-results');
  if (q.length < 2) { resultsEl.innerHTML = ''; return; }
  spSearchTimers[which] = setTimeout(function() {
    fetch('/api/search?q=' + encodeURIComponent(q) + '&limit=5')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        resultsEl.innerHTML = '';
        (data.results||[]).forEach(function(r) {
          var div = document.createElement('div');
          div.style.cssText = 'padding:4px 8px;cursor:pointer;font-size:11px;border-bottom:1px solid #21262d;';
          div.textContent = r.symbol + ' [' + r.kind + ']';
          div.onclick = function() {
            document.getElementById('sp-' + which).value = r.symbol;
            resultsEl.innerHTML = '';
          };
          resultsEl.appendChild(div);
        });
      });
  }, 200);
}

function findShortestPath() {
  var source = document.getElementById('sp-source').value.trim();
  var target = document.getElementById('sp-target').value.trim();
  var resultEl = document.getElementById('sp-result');
  if (!source || !target) { resultEl.innerHTML = '<span style="color:#f85149;">Enter both source and target symbols</span>'; return; }
  resultEl.innerHTML = 'Searching...';
  fetch('/api/shortest-path?source=' + encodeURIComponent(source) + '&target=' + encodeURIComponent(target))
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.found) {
        resultEl.innerHTML = '<span style="color:#3fb950;">Path found! Length: ' + data.length + '</span><br>' +
          (data.node_ids||[]).join(' → ');
        // Highlight in graph
        clearHighlight();
        var pathNodes = data.node_ids || [];
        pathNodes.forEach(function(nid) {
          if (!nodesDS.get(nid)) {
            var n = { id: nid, label: nid.split('.').pop(), shape: 'box', color: { background: '#484f58', border: '#8b949e' } };
            nodesDS.add(n);
          }
        });
        highlightPath(pathNodes);
        network.fit({ animation: true });
      } else {
        resultEl.innerHTML = '<span style="color:#f0883e;">No path found between ' + esc(source) + ' and ' + esc(target) + '</span>';
      }
    }).catch(function(err) { resultEl.innerHTML = '<span style="color:#f85149;">Error: ' + err.message + '</span>'; });
}

function clearShortestPath() {
  clearHighlight();
  document.getElementById('sp-result').innerHTML = '';
  document.getElementById('sp-source').value = '';
  document.getElementById('sp-target').value = '';
}
</script>"""


def render_dashboard() -> str:
    """Return complete HTML document with vis-network dashboard.

    This replaces the old Cytoscape.js renderer with a multi-panel
    dashboard that matches Understand Anything's interaction quality:
    force-directed graph, file browser, node detail panel, semantic
    annotations, guided tours, export, and shortest-path finder.
    """
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>memorygraph — Code Knowledge Graph</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.9/standalone/umd/vis-network.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
{all_css()}
</head>
<body>
{all_layout_html()}
{tours_data_json()}
{graph_init_js()}
{search_js()}
{panels_js()}
{export_js()}
{tour_js()}
{_shortest_path_js()}
{_toast_js()}
</body>
</html>"""


# Backward-compatible alias — server.py imports ``render_html`` from this package.
render_html = render_dashboard
