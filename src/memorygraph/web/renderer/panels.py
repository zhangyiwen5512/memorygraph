"""Panel JS — file browser, stats overview, node detail panel."""
from __future__ import annotations


def panels_js() -> str:
    """Return combined JS for all panels."""
    return file_browser_js() + stats_js() + detail_panel_js() + panel_toggle_js()


def file_browser_js() -> str:
    """File browser: fetch /api/files, render tree, filter."""
    return """<script>
var allFiles = [];
function loadFiles() {
  fetch('/api/files')
    .then(function(r) { return r.json(); })
    .then(function(data) { allFiles = data.files || []; renderFileTree(allFiles); })
    .catch(function() { document.getElementById('file-tree').innerHTML = '<p style="color:#f85149;font-size:11px;">Failed to load files</p>'; });
}

function renderFileTree(files) {
  var tree = buildTree(files);
  var html = renderTreeHTML(tree, '');
  document.getElementById('file-tree').innerHTML = html || '<p style="color:#484f58;font-size:11px;">No files indexed</p>';
}

function buildTree(files) {
  var root = {};
  files.forEach(function(f) {
    var parts = (f.path||'').split('/');
    var cur = root;
    for (var i = 0; i < parts.length - 1; i++) {
      if (!cur[parts[i]]) cur[parts[i]] = {_: {}};
      cur = cur[parts[i]];
    }
    var name = parts[parts.length - 1];
    cur[name] = { _file: f };
  });
  return root;
}

function renderTreeHTML(tree, prefix) {
  var html = '';
  var dirs = [], files = [];
  for (var key in tree) {
    if (key === '_') continue;
    if (tree[key]._file) files.push(key);
    else dirs.push(key);
  }
  dirs.sort(); files.sort();
  dirs.forEach(function(d) {
    html += '<div class="dir" onclick="toggleDir(event)">' + d + '</div>';
    html += '<div class="dir-children">' + renderTreeHTML(tree[d], prefix + '  ') + '</div>';
  });
  files.forEach(function(f) {
    var fi = tree[f]._file;
    html += '<div class="file" onclick="loadFileGraph(\'' + esc(fi.path) + '\')" title="' + esc(fi.path) + '">';
    html += '<span>' + esc(f) + '</span>';
    html += '<span class="sym-count">' + (fi.symbol_count||0) + '</span>';
    html += '</div>';
  });
  return html;
}

function toggleDir(e) {
  e.stopPropagation();
  e.target.classList.toggle('open');
  e.target.nextElementSibling.classList.toggle('open');
}

function loadFileGraph(filePath) {
  fetch('/api/search?q=' + encodeURIComponent(filePath) + '&limit=1')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.results && data.results.length > 0) {
        loadGraph(data.results[0].symbol, document.getElementById('depth-select').value);
      } else {
        showToast('No symbols found in ' + filePath, true);
      }
    });
}

function filterFiles() {
  var q = document.getElementById('file-filter').value.toLowerCase();
  if (!q) { renderFileTree(allFiles); return; }
  var filtered = allFiles.filter(function(f) { return (f.path||'').toLowerCase().indexOf(q) >= 0; });
  renderFileTree(filtered);
}

function esc(s) { return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
</script>"""


def stats_js() -> str:
    """Stats overview panel JS."""
    return """<script>
function loadStats() {
  fetch('/api/status')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var html = '<div class="stats-grid">';
      html += '<div class="stat-card"><div class="value">' + (data.files||0) + '</div><div class="label">Files</div></div>';
      html += '<div class="stat-card"><div class="value">' + (data.symbols||0) + '</div><div class="label">Symbols</div></div>';
      html += '<div class="stat-card"><div class="value">' + (data.edges||0) + '</div><div class="label">Edges</div></div>';
      html += '<div class="stat-card"><div class="value">' + (data.coverage||'0%') + '</div><div class="label">Coverage</div></div>';
      html += '</div>';
      document.getElementById('stats-panel').innerHTML = html;
    }).catch(function() {});
}
</script>"""


def detail_panel_js() -> str:
    """Node detail panel: fetch /api/node + /api/semantic, render sections."""
    return """<script>
var currentDetailNode = null;

function showNodeDetail(nodeId) {
  currentDetailNode = nodeId;
  var node = nodesDS.get(nodeId);
  if (!node) return;

  var file = node._file || '';
  var html = '<div style="margin-bottom:12px;">';
  html += '<span class="detail-badge badge-kind">' + esc(node._kind||'?') + '</span> ';
  if (node._role) html += '<span class="detail-badge badge-role">' + esc(node._role) + '</span> ';
  html += '</div>';
  html += '<div class="detail-section"><h4>Symbol</h4><div class="detail-value code">' + esc(nodeId) + '</div></div>';
  html += '<div class="detail-section"><h4>File</h4><div class="detail-value">' + esc(file) + ':' + (node._line||'') + '</div></div>';

  document.getElementById('detail-content').innerHTML = html + '<p style="color:#484f58;font-size:11px;">Loading details...</p>';

  // Fetch node details
  fetch('/api/node/' + encodeURIComponent(nodeId))
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var h = html;
      if (data.callers && data.callers.length > 0) {
        h += '<div class="detail-section"><h4>Callers (' + data.callers.length + ')</h4><div class="detail-callers">';
        data.callers.forEach(function(c) { h += '<a onclick="navigateToNode(\'' + esc(c.source) + '\')">' + esc(c.source) + '</a> '; });
        h += '</div></div>';
      }
      if (data.callees && data.callees.length > 0) {
        h += '<div class="detail-section"><h4>Callees (' + data.callees.length + ')</h4><div class="detail-callees">';
        data.callees.forEach(function(c) { h += '<a onclick="navigateToNode(\'' + esc(c.target) + '\')">' + esc(c.target) + '</a> '; });
        h += '</div></div>';
      }
      document.getElementById('detail-content').innerHTML = h;
    }).catch(function() {});

  // Fetch semantic data
  if (file) {
    fetch('/api/semantic?file=' + encodeURIComponent(file))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var el = document.getElementById('detail-content');
        var h = el.innerHTML;
        if (data.module_summary) {
          h += '<div class="detail-section"><h4>Module Summary</h4><div class="detail-value">' + esc(data.module_summary) + '</div></div>';
        }
        if (data.annotations) {
          data.annotations.forEach(function(a) {
            if (a.symbol && a.symbol !== nodeId && !nodeId.endsWith(a.symbol)) return;
            if (a.summary) h += '<div class="detail-section"><h4>Summary</h4><div class="detail-value">' + esc(a.summary) + '</div></div>';
            if (a.design_intent) h += '<div class="detail-section"><h4>Design Intent</h4><div class="detail-value">' + esc(a.design_intent) + '</div></div>';
            if (a.pitfalls) h += '<div class="detail-section"><h4>⚠️ Pitfalls</h4><div class="detail-value" style="color:#f0883e;">' + esc(a.pitfalls) + '</div></div>';
          });
        }
        if (data.unknowns && data.unknowns.length > 0) {
          h += '<div class="detail-section"><h4>❓ Open Questions</h4>';
          data.unknowns.forEach(function(u) { h += '<div class="detail-value" style="margin-bottom:4px;color:#d29922;">' + esc(u.question) + '</div>'; });
          h += '</div>';
        }
        if (data.insights && data.insights.length > 0) {
          h += '<div class="detail-section"><h4>💡 Insights</h4>';
          data.insights.forEach(function(i) { h += '<div class="detail-value" style="margin-bottom:4px;">' + esc(i.insight) + '</div>'; });
          h += '</div>';
        }
        el.innerHTML = h;
      }).catch(function() {});
  }
}

function navigateToNode(nodeId) {
  loadGraph(nodeId, document.getElementById('depth-select').value);
  showNodeDetail(nodeId);
}
</script>"""


def panel_toggle_js() -> str:
    """Sidebar panel toggle logic."""
    return """<script>
function toggleLeftPanel() {
  document.getElementById('left-panel').classList.toggle('collapsed');
}
function toggleRightPanel() {
  document.getElementById('right-panel').classList.toggle('collapsed');
}
</script>"""
