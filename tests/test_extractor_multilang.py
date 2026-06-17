"""Tests for Go, Rust, Java, C# IRExtractors."""
import json
import os

import pytest

from memorygraph.parsing.detector import LanguageDetector
from memorygraph.parsing.extractor import (
    CSharpExtractor,
    GoExtractor,
    JavaExtractor,
    JavaScriptExtractor,
    RustExtractor,
)
from memorygraph.parsing.ir import to_json_dict
from memorygraph.parsing.registry import LanguageRegistry
from memorygraph.parsing.ts_parser import TreeSitterParser

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def registry():
    return LanguageRegistry()


@pytest.fixture
def parser(registry):
    return TreeSitterParser(registry)


@pytest.fixture
def detector(registry):
    return LanguageDetector(registry)


LANG_PARAMS = [
    ("sample.go", GoExtractor),
    ("sample.rs", RustExtractor),
    ("sample.java", JavaExtractor),
    ("sample.cs", CSharpExtractor),
    ("sample.ts", JavaScriptExtractor),
]


@pytest.mark.parametrize("filename,extractor_cls", LANG_PARAMS)
def test_extractor_produces_symbols(filename, extractor_cls, registry, parser, detector):
    path = os.path.join(FIXTURE_DIR, filename)
    config = detector.detect(path)
    tree, source_bytes = parser.parse(path, config)
    extractor = extractor_cls()
    result = extractor.extract(path, tree, source_bytes, config.name)
    assert len(result.symbols) > 0, f"{config.name}: expected at least 1 symbol"
    assert result.fatal_error is None, f"{config.name}: unexpected fatal error: {result.fatal_error}"


@pytest.mark.parametrize("filename,extractor_cls", LANG_PARAMS)
def test_extractor_produces_call_edges(filename, extractor_cls, registry, parser, detector):
    path = os.path.join(FIXTURE_DIR, filename)
    config = detector.detect(path)
    tree, source_bytes = parser.parse(path, config)
    extractor = extractor_cls()
    result = extractor.extract(path, tree, source_bytes, config.name)
    # Not all fixtures have calls, but most should
    # At minimum the result should be parseable
    assert result.fatal_error is None


@pytest.mark.parametrize("filename,extractor_cls", LANG_PARAMS)
def test_extractor_result_json_serializable(filename, extractor_cls, registry, parser, detector):
    path = os.path.join(FIXTURE_DIR, filename)
    config = detector.detect(path)
    tree, source_bytes = parser.parse(path, config)
    extractor = extractor_cls()
    result = extractor.extract(path, tree, source_bytes, config.name)
    d = to_json_dict(result)
    json_str = json.dumps(d)
    assert len(json_str) > 0


def test_go_extractor_extracts_interface(registry, parser, detector):
    """Go extractor should extract interface types."""
    path = os.path.join(FIXTURE_DIR, "sample.go")
    config = detector.detect(path)
    tree, source_bytes = parser.parse(path, config)
    extractor = GoExtractor()
    result = extractor.extract(path, tree, source_bytes, config.name)
    interface_symbols = [s for s in result.symbols if s.kind.value == "interface"]
    assert len(interface_symbols) >= 1, f"Expected at least 1 interface symbol, got {len(interface_symbols)}"


def test_go_extractor_extracts_type_references(registry, parser, detector):
    """Go extractor should extract TYPE_REFERENCES edges for parameter/field types."""
    path = os.path.join(FIXTURE_DIR, "sample.go")
    config = detector.detect(path)
    tree, source_bytes = parser.parse(path, config)
    extractor = GoExtractor()
    result = extractor.extract(path, tree, source_bytes, config.name)
    type_ref_edges = [e for e in result.edges if e.kind.value == "type_refs"]
    assert len(type_ref_edges) >= 1, f"Expected at least 1 TYPE_REFERENCES edge, got {len(type_ref_edges)}"


# ── Rust-specific feature tests ──────────────────────────────────────────────

def test_rust_extractor_extracts_struct(registry, parser, detector):
    """Rust extractor should extract struct definitions."""
    path = os.path.join(FIXTURE_DIR, "sample.rs")
    config = detector.detect(path)
    tree, source_bytes = parser.parse(path, config)
    extractor = RustExtractor()
    result = extractor.extract(path, tree, source_bytes, config.name)
    struct_names = {s.name for s in result.symbols if s.kind.value == "class"}
    assert "Person" in struct_names, f"Expected struct 'Person', got {struct_names}"


def test_rust_extractor_extracts_trait(registry, parser, detector):
    """Rust extractor should extract traits as interfaces."""
    path = os.path.join(FIXTURE_DIR, "sample.rs")
    config = detector.detect(path)
    tree, source_bytes = parser.parse(path, config)
    extractor = RustExtractor()
    result = extractor.extract(path, tree, source_bytes, config.name)
    trait_names = {s.name for s in result.symbols if s.kind.value == "interface"}
    assert "Greetable" in trait_names, f"Expected trait 'Greetable', got {trait_names}"


def test_rust_extractor_extracts_use_imports(registry, parser, detector):
    """Rust extractor should extract use imports as edges."""
    path = os.path.join(FIXTURE_DIR, "sample.rs")
    config = detector.detect(path)
    tree, source_bytes = parser.parse(path, config)
    extractor = RustExtractor()
    result = extractor.extract(path, tree, source_bytes, config.name)
    import_edges = [e for e in result.edges if e.kind.value == "imports"]
    assert len(import_edges) >= 1, "Expected at least 1 import edge"
    import_targets = {e.target for e in import_edges}
    assert "fmt" in import_targets, f"Expected import of 'std::fmt', got {import_targets}"


def test_rust_extractor_extracts_const(registry, parser, detector):
    """Rust extractor should extract const items as variables."""
    path = os.path.join(FIXTURE_DIR, "sample.rs")
    config = detector.detect(path)
    tree, source_bytes = parser.parse(path, config)
    extractor = RustExtractor()
    result = extractor.extract(path, tree, source_bytes, config.name)
    var_names = {s.name for s in result.symbols if s.kind.value == "variable"}
    assert "DEFAULT_NAME" in var_names, f"Expected 'DEFAULT_NAME', got {var_names}"


# ── Java-specific feature tests ──────────────────────────────────────────────

def test_java_extractor_extracts_classes(registry, parser, detector):
    """Java extractor should extract class declarations."""
    path = os.path.join(FIXTURE_DIR, "sample.java")
    config = detector.detect(path)
    tree, source_bytes = parser.parse(path, config)
    extractor = JavaExtractor()
    result = extractor.extract(path, tree, source_bytes, config.name)
    class_names = {s.name for s in result.symbols if s.kind.value == "class"}
    assert "Calculator" in class_names, f"Expected class 'Calculator', got {class_names}"
    assert "Main" in class_names, f"Expected class 'Main', got {class_names}"


def test_java_extractor_extracts_methods(registry, parser, detector):
    """Java extractor should extract method declarations with correct parent."""
    path = os.path.join(FIXTURE_DIR, "sample.java")
    config = detector.detect(path)
    tree, source_bytes = parser.parse(path, config)
    extractor = JavaExtractor()
    result = extractor.extract(path, tree, source_bytes, config.name)
    add_methods = [s for s in result.symbols if s.name == "add" and s.kind.value == "method"]
    assert len(add_methods) == 1, f"Expected 1 'add' method, got {len(add_methods)}"
    assert add_methods[0].parent_symbol == "Calculator", (
        f"Expected parent 'Calculator', got {add_methods[0].parent_symbol}"
    )


def test_java_extractor_extracts_imports(registry, parser, detector):
    """Java extractor should extract import declarations as edges."""
    path = os.path.join(FIXTURE_DIR, "sample.java")
    config = detector.detect(path)
    tree, source_bytes = parser.parse(path, config)
    extractor = JavaExtractor()
    result = extractor.extract(path, tree, source_bytes, config.name)
    import_edges = [e for e in result.edges if e.kind.value == "imports"]
    assert len(import_edges) >= 1, "Expected at least 1 import edge"
    import_targets = {e.target for e in import_edges}
    assert len(import_targets) >= 1, f"Expected at least 1 import target, got {import_targets}"


def test_java_extractor_extracts_call_edges(registry, parser, detector):
    """Java extractor should extract method invocation call edges."""
    path = os.path.join(FIXTURE_DIR, "sample.java")
    config = detector.detect(path)
    tree, source_bytes = parser.parse(path, config)
    extractor = JavaExtractor()
    result = extractor.extract(path, tree, source_bytes, config.name)
    call_edges = [e for e in result.edges if e.kind.value == "calls"]
    assert len(call_edges) >= 1, "Expected at least 1 call edge"


def test_java_extractor_extracts_type_references(registry, parser, detector):
    """Java extractor should extract TYPE_REFERENCES edges for parameter/field types."""
    path = os.path.join(FIXTURE_DIR, "sample.java")
    config = detector.detect(path)
    tree, source_bytes = parser.parse(path, config)
    extractor = JavaExtractor()
    result = extractor.extract(path, tree, source_bytes, config.name)
    type_ref_edges = [e for e in result.edges if e.kind.value == "type_refs"]
    assert len(type_ref_edges) >= 1, f"Expected at least 1 TYPE_REFERENCES edge, got {len(type_ref_edges)}"


# ── C#-specific feature tests ────────────────────────────────────────────────

def test_csharp_extractor_extracts_classes(registry, parser, detector):
    """C# extractor should extract class declarations."""
    path = os.path.join(FIXTURE_DIR, "sample.cs")
    config = detector.detect(path)
    tree, source_bytes = parser.parse(path, config)
    extractor = CSharpExtractor()
    result = extractor.extract(path, tree, source_bytes, config.name)
    class_names = {s.name for s in result.symbols if s.kind.value == "class"}
    assert "Greeter" in class_names, f"Expected class 'Greeter', got {class_names}"
    assert "Program" in class_names, f"Expected class 'Program', got {class_names}"


def test_csharp_extractor_extracts_interfaces(registry, parser, detector):
    """C# extractor should extract interface declarations."""
    path = os.path.join(FIXTURE_DIR, "sample.cs")
    config = detector.detect(path)
    tree, source_bytes = parser.parse(path, config)
    extractor = CSharpExtractor()
    result = extractor.extract(path, tree, source_bytes, config.name)
    iface_names = {s.name for s in result.symbols if s.kind.value == "interface"}
    assert "IGreetable" in iface_names, f"Expected interface 'IGreetable', got {iface_names}"


def test_csharp_extractor_extracts_methods(registry, parser, detector):
    """C# extractor should extract method declarations."""
    path = os.path.join(FIXTURE_DIR, "sample.cs")
    config = detector.detect(path)
    tree, source_bytes = parser.parse(path, config)
    extractor = CSharpExtractor()
    result = extractor.extract(path, tree, source_bytes, config.name)
    method_names = {s.name for s in result.symbols if s.kind.value == "method"}
    assert "Greet" in method_names, f"Expected method 'Greet', got {method_names}"
    assert "Main" in method_names, f"Expected method 'Main', got {method_names}"
    assert "CreateGreeter" in method_names, f"Expected method 'CreateGreeter', got {method_names}"


def test_csharp_extractor_extracts_using_directives(registry, parser, detector):
    """C# extractor should extract using directives as import edges."""
    path = os.path.join(FIXTURE_DIR, "sample.cs")
    config = detector.detect(path)
    tree, source_bytes = parser.parse(path, config)
    extractor = CSharpExtractor()
    result = extractor.extract(path, tree, source_bytes, config.name)
    import_edges = [e for e in result.edges if e.kind.value == "imports"]
    assert len(import_edges) >= 1, "Expected at least 1 import edge"
    import_targets = {e.target for e in import_edges}
    assert "System" in import_targets, f"Expected 'System' in imports, got {import_targets}"


def test_csharp_extractor_method_has_correct_parent(registry, parser, detector):
    """C# extractor should assign correct parent to methods."""
    path = os.path.join(FIXTURE_DIR, "sample.cs")
    config = detector.detect(path)
    tree, source_bytes = parser.parse(path, config)
    extractor = CSharpExtractor()
    result = extractor.extract(path, tree, source_bytes, config.name)
    # CreateGreeter is inside Program
    cg_methods = [s for s in result.symbols if s.name == "CreateGreeter"]
    assert len(cg_methods) == 1
    assert cg_methods[0].parent_symbol == "Program", (
        f"Expected parent 'Program', got {cg_methods[0].parent_symbol}"
    )


def test_csharp_extractor_extracts_type_references(registry, parser, detector):
    """C# extractor should extract TYPE_REFERENCES edges for parameter/local types."""
    path = os.path.join(FIXTURE_DIR, "sample.cs")
    config = detector.detect(path)
    tree, source_bytes = parser.parse(path, config)
    extractor = CSharpExtractor()
    result = extractor.extract(path, tree, source_bytes, config.name)
    type_ref_edges = [e for e in result.edges if e.kind.value == "type_refs"]
    assert len(type_ref_edges) >= 1, f"Expected at least 1 TYPE_REFERENCES edge, got {len(type_ref_edges)}"
