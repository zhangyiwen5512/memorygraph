"""vis-network graph visualization — init, physics, node/edge styling, interaction."""
from __future__ import annotations


def graph_init_js() -> str:
    """Return JS that initializes the vis-network graph."""
    return """<script>
// ── Color maps ──
var KIND_COLORS = {
  'function': {bg:'#1f6feb', border:'#58a6ff', shape:'box'},
  'method': {bg:'#1f6feb', border:'#58a6ff', shape:'box'},
  'class': {bg:'#238636', border:'#3fb950', shape:'diamond'},
  'interface': {bg:'#a371f7', border:'#c8a2ff', shape:'diamond'},
  'type': {bg:'#a371f7', border:'#c8a2ff', shape:'ellipse'},
  'variable': {bg:'#d29922', border:'#e2b641', shape:'ellipse'}
};
var LAYER_COLORS = {
  'api': '#f85149', 'service': '#1f6feb', 'data': '#238636',
  'ui': '#a371f7', 'utility': '#d29922', 'config': '#8b949e', 'other': '#484f58'
};
var LAYER_NAMES = {
  'api':'API', 'service':'Service', 'data':'Data',
  'ui':'UI', 'utility':'Utility', 'config':'Config', 'other':'Other'
};

// ── vis-network ──
var network = null;
var nodesDS = new vis.DataSet([]);
var edgesDS = new vis.DataSet([]);
var expandedNodes = {};
var currentRoot = null;
var highlightedPath = [];

function initGraph() {
  var container = document.getElementById('graph-container');
  var data = { nodes: nodesDS, edges: edgesDS };
  var options = {
    physics: {
      solver: 'barnesHut',
      barnesHut: { gravitationalConstant: -3000, centralGravity: 0.3, springLength: 150, springConstant: 0.04, damping: 0.3 },
      stabilization: { iterations: 100, fit: true }
    },
    interaction: { hover: true, tooltipDelay: 100, zoomView: true, dragView: true, navigationButtons: false },
    nodes: { font: { color: '#c9d1d9', size: 11, face: 'system-ui' }, borderWidth: 2, shadow: {enabled:true, size:3} },
    edges: { color: { color: '#30363d', hover: '#58a6ff' }, width: 1.2, arrows: { to: { enabled: true, scaleFactor: 0.6 } }, smooth: { type: 'continuous' } },
    layout: { improvedLayout: false },
    groups: {
      'api': { borderWidth: 3, borderWidthSelected: 4 },
      'service': { borderWidth: 3, borderWidthSelected: 4 },
      'data': { borderWidth: 3, borderWidthSelected: 4 },
      'ui': { borderWidth: 3, borderWidthSelected: 4 },
      'utility': { borderWidth: 3, borderWidthSelected: 4 },
      'config': { borderWidth: 3, borderWidthSelected: 4 },
      'other': { borderWidth: 3, borderWidthSelected: 4 }
    }
  };
  network = new vis.Network(container, data, options);

  network.on('selectNode', function(params) {
    if (params.nodes.length > 0) showNodeDetail(params.nodes[0]);
  });
  network.on('deselectNode', function() { /* keep detail panel */ });
  network.on('doubleClick', function(params) {
    if (params.nodes.length > 0) expandNode(params.nodes[0]);
  });

  // Load initial graph from the first search or leave empty with instructions
  drawLegend();
  loadLayers();
}

// ── Adaptive physics ──
function applyAdaptivePhysics() {
  var count = nodesDS.length;
  if (count < 100) {
    network.setOptions({ physics: { enabled: true, solver: 'barnesHut',
      barnesHut: { gravitationalConstant: -3000, centralGravity: 0.3, springLength: 150, springConstant: 0.04, damping: 0.3 },
      stabilization: { iterations: 100, fit: true } } });
  } else if (count < 300) {
    network.setOptions({ physics: { enabled: true, solver: 'barnesHut',
      barnesHut: { gravitationalConstant: -2000, centralGravity: 0.3, springLength: 120, springConstant: 0.03, damping: 0.4 },
      stabilization: { iterations: 50, fit: true } } });
  } else {
    network.setOptions({ physics: { enabled: false },
      layout: { hierarchical: { enabled: true, direction: 'UD', sortMethod: 'directed', nodeSpacing: 100, levelSeparation: 150 } } });
  }
}

// ── Graph loading ──
function loadGraph(root, depth) {
  currentRoot = root;
  showStatus('Loading...');
  fetch('/api/graph?root=' + encodeURIComponent(root) + '&depth=' + (depth||2))
    .then(function(r) { if(!r.ok) throw new Error(r.statusText); return r.json(); })
    .then(function(data) {
      nodesDS.clear(); edgesDS.clear(); expandedNodes = {};
      data.nodes.forEach(function(n) { addNode(n, false); });
      data.edges.forEach(function(e) { addEdge(e); });
      // Truncation awareness
      if (data.truncated) {
        window._truncatedBranches = data.truncated_branches || [];
        (data.truncated_branches||[]).forEach(function(b) {
          var fid = '__folded__' + b.symbol + '__' + b.direction;
          if (!nodesDS.get(fid)) {
            nodesDS.add({
              id: fid, label: '+' + b.direction + 's', shape: 'dot',
              color: { background: '#30363d', border: '#f0883e' },
              borderWidth: 2, borderWidthSelected: 3,
              _folded: true, _from: b.symbol, _direction: b.direction
            });
            edgesDS.add({ from: b.symbol, to: fid, dashes: true,
              color: { color: '#f0883e' } });
          }
        });
      }
      applyAdaptivePhysics();
      network.fit({ animation: { duration: 500, easingFunction: 'easeInOutQuad' } });
      var statusMsg = nodesDS.length + ' nodes, ' + edgesDS.length + ' edges';
      if (data.truncated) {
        statusMsg += ' (showing ' + data.nodes.length + ' of ' + data.total_available + ')';
      }
      showStatus(statusMsg);
    })
    .catch(function(err) { showStatus('Error: ' + err.message, true); });
}

function expandNode(nodeId) {
  // Handle folded nodes (truncation placeholder)
  if (nodeId.startsWith('__folded__')) {
    var n = nodesDS.get(nodeId);
    if (n && n._from) {
      loadGraph(n._from, document.getElementById('depth-select').value);
    }
    return;
  }
  if (expandedNodes[nodeId]) {
    // Collapse: remove children
    var children = nodesDS.get({ filter: function(n) { return n._parent === nodeId; } });
    children.forEach(function(n) { nodesDS.remove(n.id); });
    expandedNodes[nodeId] = false;
    return;
  }
  expandedNodes[nodeId] = true;
  fetch('/api/graph?root=' + encodeURIComponent(nodeId) + '&depth=1')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      data.nodes.forEach(function(n) {
        if (n.id === nodeId || nodesDS.get(n.id)) return;
        addNode(n, true, nodeId);
      });
      data.edges.forEach(function(e) { addEdge(e); });
      var depth = document.getElementById('depth-select').value;
      var statusMsg = nodesDS.length + ' nodes, ' + edgesDS.length + ' edges';
      if (data.truncated) {
        statusMsg += ' (showing ' + data.nodes.length + ' of ' + data.total_available + ')';
      }
      showStatus(statusMsg);
    });
}

function reloadGraph() {
  if (currentRoot) loadGraph(currentRoot, document.getElementById('depth-select').value);
}

function fitGraph() {
  network.fit({ animation: { duration: 300, easingFunction: 'easeInOutQuad' } });
}

// ── Node/edge manipulation ──
function addNode(n, isChild, parent) {
  var kindCfg = KIND_COLORS[n.kind] || {bg:'#484f58', border:'#8b949e', shape:'box'};
  var label = (n.id||'').split('.').pop() || n.id || '?';
  if (n.role) label += ' [' + n.role + ']';
  var nodeObj = {
    id: n.id,
    label: label,
    shape: kindCfg.shape,
    color: { background: kindCfg.bg, border: kindCfg.border },
    title: '<b>' + n.id + '</b><br>' + (n.kind||'') + ' · ' + (n.file||'') + ':' + (n.line||''),
    _file: n.file || '', _kind: n.kind || '', _line: n.line || '',
    _role: n.role || '', _complexity: n.complexity || 0, _pattern: n.pattern || '',
    _layer: n._layer || n.layer || 'other'
  };
  if (isChild) nodeObj._parent = parent;
  if (n.pattern) nodeObj.borderWidth = 4;
  nodesDS.add(nodeObj);
}

function addEdge(e) {
  var edgeId = e.source + '→' + e.target;
  if (edgesDS.get(edgeId)) return;
  edgesDS.add({ id: edgeId, from: e.source, to: e.target, title: e.kind || 'calls' });
}

// ── Layers ──
var nodeLayers = {};
function loadLayers() {
  fetch('/api/graph/layers')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      for (var layer in data.layers) {
        data.layers[layer].nodes.forEach(function(nid) { nodeLayers[nid] = layer; });
      }
    }).catch(function(){});
}

// ── Legend ──
function drawLegend() {
  var html = '<div class="legend-group">';
  for (var k in KIND_COLORS) {
    html += '<div class="legend-item"><div class="legend-dot" style="background:'+KIND_COLORS[k].bg+'"></div>'+k+'</div>';
  }
  html += '</div><div class="legend-group" style="margin-left:8px;padding-left:8px;border-left:1px solid #30363d;">';
  for (var l in LAYER_COLORS) {
    if (l==='other') continue;
    html += '<div class="legend-item"><div class="legend-square" style="background:'+LAYER_COLORS[l]+'"></div>'+LAYER_NAMES[l]+'</div>';
  }
  html += '</div>';
  document.getElementById('legend').innerHTML = html;
}

// ── Layout change ──
function changeLayout() {
  var layout = document.getElementById('layout-select').value;
  if (layout === 'force') {
    network.setOptions({ physics: { enabled: true }, layout: { hierarchical: false } });
    network.stabilize(50);
  } else {
    network.setOptions({ physics: { enabled: false }, layout: { hierarchical: { enabled: true, direction: 'UD', sortMethod: 'directed', nodeSpacing: 120, levelSeparation: 150 } } });
  }
}

// ── Shortest path highlighting ──
function highlightPath(pathNodes) {
  clearHighlight();
  highlightedPath = pathNodes;
  pathNodes.forEach(function(nid) {
    var n = nodesDS.get(nid);
    if (n) nodesDS.update({ id: nid, color: { background: '#f0883e', border: '#ffb366' }, borderWidth: 4 });
  });
  for (var i = 0; i < pathNodes.length - 1; i++) {
    var eid1 = pathNodes[i] + '→' + pathNodes[i+1];
    var eid2 = pathNodes[i+1] + '→' + pathNodes[i];
    var e = edgesDS.get(eid1) || edgesDS.get(eid2);
    if (e) edgesDS.update({ id: e.id, color: { color: '#f0883e' }, width: 3 });
  }
}

function clearHighlight() {
  highlightedPath.forEach(function(nid) {
    var n = nodesDS.get(nid);
    if (n) {
      var kindCfg = KIND_COLORS[n._kind] || {bg:'#484f58', border:'#8b949e'};
      nodesDS.update({ id: nid, color: { background: kindCfg.bg, border: kindCfg.border }, borderWidth: n._pattern ? 4 : 2 });
    }
  });
  // Reset edge colors
  edgesDS.forEach(function(e) {
    edgesDS.update({ id: e.id, color: { color: '#30363d', hover: '#58a6ff' }, width: 1.2 });
  });
  highlightedPath = [];
}

// ── Status helpers ──
function showStatus(msg, isError) {
  var el = document.getElementById('status-left');
  el.textContent = msg;
  el.style.color = isError ? '#f85149' : '#484f58';
}

// ── SSE ──
var evtSource = new EventSource('/api/events');
evtSource.addEventListener('graph-changed', function() {
  if (currentRoot) reloadGraph();
});

// ── Keyboard shortcuts ──
document.addEventListener('keydown', function(e) {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') {
    if (e.key === 'Escape') { e.target.blur(); closeAllModals(); }
    return;
  }
  if (e.key === '/' || (e.ctrlKey && e.key === 'k')) {
    e.preventDefault();
    document.getElementById('search-input').focus();
  } else if (e.key === 'Escape') {
    closeAllModals();
  } else if (e.key === '=' || e.key === '+') {
    if (network) network.moveTo({ scale: network.getScale() * 1.2 });
  } else if (e.key === '-') {
    if (network) network.moveTo({ scale: network.getScale() / 1.2 });
  } else if (e.key === 'r') {
    if (network) network.fit({ animation: true });
  }
});

function closeAllModals() {
  document.querySelectorAll('.modal-backdrop.open').forEach(function(m) { m.classList.remove('open'); });
  document.getElementById('tour-backdrop').classList.remove('open');
  document.getElementById('tour-card').style.display = 'none';
}

// Initialize on load
document.addEventListener('DOMContentLoaded', function() { initGraph(); loadStats(); loadFiles(); });
</script>"""
