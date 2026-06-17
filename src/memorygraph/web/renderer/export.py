"""Export JS — PNG/SVG/JSON download."""
from __future__ import annotations


def export_js() -> str:
    """Return JS for export modal and download logic."""
    return """<script>
function openExportModal() {
  document.getElementById('export-modal').classList.add('open');
}
function closeExportModal() {
  document.getElementById('export-modal').classList.remove('open');
}

function doExport() {
  var fmt = document.querySelector('input[name="export-fmt"]:checked').value;
  if (fmt === 'png') exportPNG();
  else if (fmt === 'svg') exportSVG();
  else if (fmt === 'json') exportJSON();
  closeExportModal();
}

function exportPNG() {
  if (typeof html2canvas === 'undefined') {
    showToast('html2canvas library not loaded. Try SVG or JSON export.', true); return;
  }
  var container = document.getElementById('graph-container');
  html2canvas(container, { backgroundColor: '#0d1117' }).then(function(canvas) {
    canvas.toBlob(function(blob) { downloadBlob(blob, 'memorygraph-export.png'); });
  }).catch(function() { showToast('PNG export failed', true); });
}

function exportSVG() {
  if (!network) { showToast('No graph to export', true); return; }
  try {
    var svgData = network.canvasToSVG ? network.canvas.frame.canvas.toDataURL('image/svg+xml') : null;
    if (!svgData) {
      // vis-network doesn't directly expose SVG; alert user
      showToast('SVG export not supported by vis-network directly. Use JSON or PNG.', true);
      return;
    }
  } catch(e) {
    showToast('SVG export failed. Try JSON or PNG.', true);
  }
}

function exportJSON() {
  fetch('/api/graph/full')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
      downloadBlob(blob, 'memorygraph-export.json');
    }).catch(function() { showToast('JSON export failed', true); });
}

function downloadBlob(blob, filename) {
  var url = URL.createObjectURL(blob);
  var a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click();
  document.body.removeChild(a); URL.revokeObjectURL(url);
  showToast('Downloaded: ' + filename, false);
}
</script>"""
