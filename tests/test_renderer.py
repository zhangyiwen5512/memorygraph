"""Tests for the L6 dashboard renderer package."""
from __future__ import annotations

from memorygraph.web.renderer import render_dashboard, render_html
from memorygraph.web.renderer.layout import (
    all_layout_html,
    export_modal_html,
    main_layout_html,
    shortest_path_modal_html,
    status_bar_html,
    toolbar_html,
    tour_overlay_html,
)
from memorygraph.web.renderer.styles import all_css
from memorygraph.web.renderer.tours import tours_data_json


class TestRendererDashboard:
    """Tests for the main dashboard renderer."""

    def test_render_dashboard_returns_html(self):
        """Dashboard output is a non-empty HTML document."""
        html = render_dashboard()
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html
        assert len(html) > 1000

    def test_render_html_is_alias_for_render_dashboard(self):
        """render_html is the backward-compatible alias."""
        assert render_html is render_dashboard

    def test_dashboard_uses_vis_network(self):
        """Dashboard loads vis-network from CDN (not Cytoscape.js)."""
        html = render_dashboard()
        assert "vis-network" in html
        assert "cytoscape" not in html.lower()

    def test_dashboard_has_three_column_layout(self):
        """Dashboard HTML contains all three layout panels."""
        html = render_dashboard()
        assert 'id="graph-container"' in html
        assert 'id="left-panel"' in html
        assert 'id="right-panel"' in html

    def test_dashboard_has_toolbar(self):
        """Dashboard toolbar has search, controls, and action buttons."""
        html = render_dashboard()
        assert 'id="search-input"' in html
        assert 'id="depth-select"' in html
        assert 'id="layout-select"' in html

    def test_dashboard_has_export_modal(self):
        """Export modal exists with PNG/SVG/JSON format options."""
        html = render_dashboard()
        assert 'id="export-modal"' in html
        assert "png" in html.lower()

    def test_dashboard_has_tour_overlay(self):
        """Tour overlay HTML is present."""
        html = render_dashboard()
        assert 'id="tour-card"' in html
        assert 'id="tour-backdrop"' in html

    def test_dashboard_has_status_bar(self):
        """Status bar with node/edge counts is present."""
        html = render_dashboard()
        assert 'id="status-bar"' in html

    def test_dashboard_has_shortest_path_modal(self):
        """Shortest path finder modal is present."""
        html = render_dashboard()
        assert 'id="shortest-path-modal"' in html

    def test_dashboard_has_file_browser(self):
        """File browser panel is present."""
        html = render_dashboard()
        assert 'id="file-tree"' in html
        assert 'id="stats-panel"' in html

    def test_dashboard_has_detail_panel(self):
        """Node detail panel is present."""
        html = render_dashboard()
        assert 'id="detail-content"' in html

    def test_dashboard_includes_default_tour_data(self):
        """Default tour data is embedded."""
        html = render_dashboard()
        assert "getting-started" in html

    def test_dashboard_includes_search_js(self):
        """Search JS functions are present."""
        html = render_dashboard()
        assert "searchAsYouType" in html
        assert "selectSearchResult" in html

    def test_dashboard_includes_graph_js(self):
        """Graph JS initialization is present."""
        html = render_dashboard()
        assert "vis.Network" in html
        assert "initGraph" in html

    def test_dashboard_includes_export_js(self):
        """Export JS functions are present."""
        html = render_dashboard()
        assert "doExport" in html
        assert "exportPNG" in html or "html2canvas" in html

    def test_dashboard_includes_tour_js(self):
        """Tour JS functions are present."""
        html = render_dashboard()
        assert "startTour" in html
        assert "tourNext" in html


class TestLayoutModule:
    """Tests for individual layout functions."""

    def test_toolbar_html(self):
        assert "search-input" in toolbar_html()
        assert "depth-select" in toolbar_html()

    def test_main_layout_html(self):
        html = main_layout_html()
        assert "graph-container" in html
        assert "left-panel" in html
        assert "right-panel" in html

    def test_status_bar_html(self):
        assert "status-bar" in status_bar_html()

    def test_export_modal_html(self):
        assert "export-modal" in export_modal_html()

    def test_shortest_path_modal_html(self):
        assert "shortest-path-modal" in shortest_path_modal_html()

    def test_tour_overlay_html(self):
        assert "tour-card" in tour_overlay_html()

    def test_all_layout_html_includes_all(self):
        html = all_layout_html()
        assert "toolbar" in html
        assert "graph-container" in html
        assert "status-bar" in html
        assert "modal" in html


class TestStylesModule:
    """Tests for the CSS module."""

    def test_all_css_returns_style_tag(self):
        css = all_css()
        assert "<style>" in css
        assert "</style>" in css

    def test_all_css_contains_key_selectors(self):
        css = all_css()
        assert "#graph-container" in css
        assert "#left-panel" in css
        assert "#right-panel" in css
        assert "#search-results" in css
        assert "#toolbar" in css
        assert ".modal-backdrop" in css
        assert "#tour-backdrop" in css


class TestToursModule:
    """Tests for the tour system."""

    def test_tours_data_json_has_default_tour(self):
        data = tours_data_json()
        assert "getting-started" in data
        assert "Getting Started" in data
        assert "steps" in data

    def test_tours_data_json_has_script_tags(self):
        data = tours_data_json()
        assert "<script>" in data
        assert "</script>" in data
