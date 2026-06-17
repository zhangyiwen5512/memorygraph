"""Enhanced search with debounce, keyboard navigation, typeahead dropdown."""
from __future__ import annotations


def search_js() -> str:
    """Return JS for enhanced search functionality."""
    return """<script>
var searchTimer = null;
var searchIndex = -1;

function searchAsYouType() {
  clearTimeout(searchTimer);
  var q = document.getElementById('search-input').value.trim();
  var dropdown = document.getElementById('search-results');
  if (q.length < 2) { dropdown.classList.remove('show'); return; }
  searchTimer = setTimeout(function() {
    fetch('/api/search?q=' + encodeURIComponent(q) + '&limit=8')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        dropdown.innerHTML = '';
        searchIndex = -1;
        if (!data.results || data.results.length === 0) {
          dropdown.innerHTML = '<div style="color:#484f58;justify-content:center;">No results</div>';
          dropdown.classList.add('show');
          return;
        }
        data.results.forEach(function(r, i) {
          var div = document.createElement('div');
          div.innerHTML = '<span>' + esc(r.symbol) + '</span><span class="kind-badge">' + esc(r.kind||'') + '</span>';
          div.setAttribute('data-index', i);
          div.onclick = function() { selectSearchResult(r); };
          dropdown.appendChild(div);
        });
        dropdown.classList.add('show');
      })
      .catch(function() {});
  }, 250);
}

function searchKeyDown(e) {
  var dropdown = document.getElementById('search-results');
  var items = dropdown.querySelectorAll('div[data-index]');
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    searchIndex = Math.min(searchIndex + 1, items.length - 1);
    updateSearchFocus(items);
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    searchIndex = Math.max(searchIndex - 1, -1);
    updateSearchFocus(items);
  } else if (e.key === 'Enter') {
    e.preventDefault();
    if (searchIndex >= 0 && items[searchIndex]) {
      items[searchIndex].click();
    } else {
      // Direct search with first character
      var q = document.getElementById('search-input').value.trim();
      if (q) doDirectSearch(q);
    }
  } else if (e.key === 'Escape') {
    dropdown.classList.remove('show');
    document.getElementById('search-input').blur();
  }
}

function updateSearchFocus(items) {
  items.forEach(function(item, i) {
    if (i === searchIndex) item.classList.add('focused');
    else item.classList.remove('focused');
  });
}

function selectSearchResult(r) {
  document.getElementById('search-results').classList.remove('show');
  document.getElementById('search-input').value = r.symbol;
  loadGraph(r.symbol, document.getElementById('depth-select').value);
}

function doDirectSearch(q) {
  document.getElementById('search-results').classList.remove('show');
  fetch('/api/search?q=' + encodeURIComponent(q) + '&limit=1')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.results && data.results.length > 0) {
        loadGraph(data.results[0].symbol, document.getElementById('depth-select').value);
      } else {
        showStatus('No results for: ' + q, true);
      }
    });
}

// Close dropdown on outside click
document.addEventListener('click', function(e) {
  if (!e.target.closest('.search-wrapper')) {
    document.getElementById('search-results').classList.remove('show');
  }
});
</script>"""
