"""Guided tour overlay JS — step-by-step walkthrough."""
from __future__ import annotations


def tour_js() -> str:
    """Return JS for guided tour overlay logic."""
    return """<script>
var currentTour = null;
var currentStep = 0;

function startTour(tourId) {
  fetch('/api/tours')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var tour = null;
      (data.tours||[]).forEach(function(t) { if (t.id === tourId) tour = t; });
      if (!tour && data.tours && data.tours.length > 0) tour = data.tours[0];
      if (!tour) { showToast('No tours available', true); return; }
      currentTour = tour;
      currentStep = 0;
      document.getElementById('tour-backdrop').classList.add('open');
      renderTourStep();
    }).catch(function() { showToast('Failed to load tours', true); });
}

function renderTourStep() {
  var step = currentTour.steps[currentStep];
  if (!step) { tourSkip(); return; }
  var card = document.getElementById('tour-card');
  card.style.display = 'block';
  document.getElementById('tour-title').textContent = (currentStep+1) + '. ' + (step.title||'');
  document.getElementById('tour-content').textContent = step.content||'';
  document.getElementById('tour-progress').textContent = 'Step ' + (currentStep+1) + ' of ' + currentTour.steps.length;

  // Position card near the target element
  if (step.element) {
    var el = document.querySelector(step.element);
    if (el) {
      var rect = el.getBoundingClientRect();
      var pos = step.position || 'bottom';
      card.classList.remove('top', 'bottom', 'left', 'right');
      card.classList.add(pos);
      if (pos === 'bottom') {
        card.style.top = (rect.bottom + 12) + 'px';
        card.style.left = Math.max(10, rect.left) + 'px';
      } else if (pos === 'top') {
        card.style.top = Math.max(10, rect.top - card.offsetHeight - 12) + 'px';
        card.style.left = Math.max(10, rect.left) + 'px';
      }
    }
  } else {
    // Center the card
    card.style.top = '20%'; card.style.left = '50%';
    card.style.transform = 'translate(-50%, 0)';
  }

  // Update nav buttons
  document.getElementById('tour-prev-btn').style.display = currentStep > 0 ? '' : 'none';
  document.getElementById('tour-next-btn').textContent = currentStep >= currentTour.steps.length - 1 ? 'Done ✓' : 'Next →';
}

function tourNext() {
  if (currentStep >= currentTour.steps.length - 1) { tourSkip(); return; }
  currentStep++;
  renderTourStep();
}

function tourPrev() {
  if (currentStep > 0) { currentStep--; renderTourStep(); }
}

function tourSkip() {
  document.getElementById('tour-backdrop').classList.remove('open');
  document.getElementById('tour-card').style.display = 'none';
  currentTour = null;
  currentStep = 0;
}
</script>"""


def tours_data_json() -> str:
    """Return default 'getting-started' tour as inline JSON for initial bootstrap.

    This tour is embedded directly so it works even before /api/tours
    has any files on disk.  The API is still the primary source; this is
    the fallback when ``.memorygraph/tours/`` is empty.
    """
    return r"""
<script>
// Default tour — served as fallback when /api/tours returns no tours.
window._DEFAULT_TOURS = [{
  "id": "getting-started",
  "title": "Getting Started with memorygraph",
  "description": "Learn to navigate your code knowledge graph",
  "steps": [
    {"title": "Welcome!", "content": "This is your interactive code knowledge graph. Let's take a quick tour to learn how to explore it.", "element": "#graph-container", "position": "top"},
    {"title": "Search for Symbols", "content": "Type a function, class, or method name here to find it in the graph. Try searching for a symbol you know!", "element": "#search-input", "position": "bottom"},
    {"title": "Explore the Graph", "content": "Click any node to see its details on the right. Double-click to expand and see what calls it (and what it calls). Drag nodes to rearrange.", "element": "#graph-container", "position": "top"},
    {"title": "Node Details", "content": "When you select a node, the detail panel shows: callers, callees, semantic annotations, design intent, pitfalls, and open questions.", "element": "#right-panel", "position": "left"},
    {"title": "File Browser", "content": "Browse your project files here. Click any file to jump to its symbols in the graph. Use the filter to find files quickly.", "element": "#left-panel", "position": "right"},
    {"title": "Export & Share", "content": "Export the graph as PNG, SVG, or JSON. Use the Path tool to find the shortest call chain between any two symbols.", "element": "#btn-export", "position": "bottom"},
    {"title": "You're ready!", "content": "Start exploring: type a symbol name, click nodes, and discover how your codebase fits together. Press / at any time to search.", "element": "#search-input", "position": "bottom"}
  ]
}];
</script>"""
