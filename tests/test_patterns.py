"""Tests for static design pattern detection."""
from memorygraph.semantic.patterns import (
    _detect_decorator,
    _detect_factory,
    _detect_observer,
    _detect_repository,
    _detect_singleton,
    _detect_strategy,
    detect_patterns,
)


def make_symbol(name, kind="class", qualified_name=None, parent_class=None, signature=""):
    """Helper to create symbol dicts matching the format patterns expects."""
    return {
        "name": name,
        "kind": kind,
        "qualified_name": qualified_name or name,
        "parent_class": parent_class,
        "signature": signature,
    }


class TestSingletonDetection:
    def test_name_contains_singleton(self):
        syms = [make_symbol("ConfigSingleton", "class")]
        results = _detect_singleton(syms)
        assert len(results) == 1
        assert results[0]["pattern"] == "Singleton"
        assert results[0]["confidence"] == "medium"

    def test_name_contains_instance(self):
        syms = [make_symbol("DB_Instance", "class")]
        results = _detect_singleton(syms)
        assert len(results) == 1
        assert results[0]["pattern"] == "Singleton"

    def test_has_get_instance_method(self):
        syms = [make_symbol("Config", "class", signature="def get_instance(cls)")]
        results = _detect_singleton(syms)
        assert any(r["confidence"] == "high" for r in results)

    def test_has_getInstance_method(self):
        syms = [make_symbol("Config", "class", signature="def getInstance(cls)")]
        results = _detect_singleton(syms)
        assert any(r["confidence"] == "high" for r in results)

    def test_non_class_ignored(self):
        syms = [make_symbol("singleton_helper", "function")]
        results = _detect_singleton(syms)
        assert len(results) == 0

    def test_ordinary_class_not_detected(self):
        syms = [make_symbol("Utils", "class")]
        results = _detect_singleton(syms)
        assert len(results) == 0


class TestFactoryDetection:
    def test_name_contains_factory(self):
        syms = [make_symbol("UserFactory", "class")]
        results = _detect_factory(syms, {})
        assert len(results) == 1
        assert results[0]["pattern"] == "Factory"
        assert results[0]["confidence"] == "medium"

    def test_name_contains_builder(self):
        syms = [make_symbol("QueryBuilder", "class")]
        results = _detect_factory(syms, {})
        assert len(results) == 1
        assert results[0]["pattern"] == "Factory"

    def test_function_returns_type(self):
        syms = [make_symbol("create_user", "function",
                            qualified_name="create_user",
                            signature="def create_user() -> User:")]
        callees = {"create_user": ["User.__init__", "User.validate"]}
        results = _detect_factory(syms, callees)
        assert any(r["confidence"] == "low" and "User" in r["evidence"]
                   for r in results)

    def test_ordinary_class_not_detected_as_factory(self):
        syms = [make_symbol("User", "class")]
        results = _detect_factory(syms, {})
        assert len(results) == 0


class TestObserverDetection:
    def test_subscribe_method(self):
        syms = [make_symbol("subscribe", "method", qualified_name="EventBus.subscribe")]
        results = _detect_observer(syms, {}, {})
        assert len(results) >= 1
        obs_sym = [r for r in results if r["symbol"] == "EventBus.subscribe"]
        assert len(obs_sym) >= 1

    def test_add_listener_method(self):
        syms = [make_symbol("add_listener", "method", qualified_name="Bus.add_listener")]
        results = _detect_observer(syms, {}, {})
        assert any(r["symbol"] == "Bus.add_listener" for r in results)

    def test_on_method(self):
        syms = [make_symbol("on_connect", "method", qualified_name="Socket.on_connect")]
        results = _detect_observer(syms, {}, {})
        assert any(r["symbol"] == "Socket.on_connect" for r in results)

    def test_notify_method(self):
        syms = [make_symbol("notify", "method", qualified_name="EventBus.notify")]
        results = _detect_observer(syms, {}, {})
        assert any(r["confidence"] == "medium" for r in results)

    def test_emit_method(self):
        syms = [make_symbol("emit", "method",
                            qualified_name="socket.emit",
                            parent_class="socket")]
        results = _detect_observer(syms, {}, {})
        assert any(r["symbol"] == "socket.emit" for r in results)

    def test_register_method(self):
        syms = [make_symbol("register_handler", "method")]
        results = _detect_observer(syms, {}, {})
        assert len(results) >= 1


class TestStrategyDetection:
    def test_multiple_implementations(self):
        syms = [
            make_symbol("PaymentStrategy", "class"),
            make_symbol("CreditCardPayment", "class", parent_class="PaymentStrategy"),
            make_symbol("PayPalPayment", "class", parent_class="PaymentStrategy"),
        ]
        results = _detect_strategy(syms)
        assert len(results) == 1
        assert results[0]["pattern"] == "Strategy"
        assert results[0]["symbol"] == "PaymentStrategy"
        assert "2 implementations" in results[0]["evidence"]

    def test_single_child_not_strategy(self):
        syms = [
            make_symbol("Base", "class"),
            make_symbol("Child", "class", parent_class="Base"),
        ]
        results = _detect_strategy(syms)
        assert len(results) == 0

    def test_no_inheritance_not_strategy(self):
        syms = [
            make_symbol("A", "class"),
            make_symbol("B", "class"),
        ]
        results = _detect_strategy(syms)
        assert len(results) == 0


class TestDecoratorDetection:
    def test_name_contains_decorator(self):
        syms = [make_symbol("LoggingDecorator", "class")]
        results = _detect_decorator(syms)
        assert len(results) == 1
        assert results[0]["pattern"] == "Decorator"

    def test_name_contains_wrapper(self):
        syms = [make_symbol("APIWrapper", "class")]
        results = _detect_decorator(syms)
        assert len(results) >= 1

    def test_constructor_with_component_param(self):
        syms = [make_symbol("Wrapper", "class",
                            signature="def __init__(self, component):")]
        results = _detect_decorator(syms)
        assert len(results) >= 1

    def test_constructor_with_delegate_param(self):
        syms = [make_symbol("Proxy", "class",
                            signature="def __init__(self, delegate):")]
        results = _detect_decorator(syms)
        assert len(results) >= 1

    def test_ordinary_class_not_decorator(self):
        syms = [make_symbol("Config", "class")]
        results = _detect_decorator(syms)
        assert len(results) == 0


class TestRepositoryDetection:
    def test_name_contains_repository(self):
        syms = [make_symbol("UserRepository", "class")]
        results = _detect_repository(syms)
        assert len(results) == 1
        assert results[0]["pattern"] == "Repository"
        assert results[0]["confidence"] == "high"

    def test_name_contains_store(self):
        syms = [make_symbol("TaskStore", "class")]
        results = _detect_repository(syms)
        assert len(results) == 1
        assert results[0]["pattern"] == "Repository"

    def test_name_contains_dao(self):
        syms = [make_symbol("CustomerDAO", "class")]
        results = _detect_repository(syms)
        assert len(results) == 1
        assert results[0]["pattern"] == "Repository"

    def test_name_contains_repo(self):
        syms = [make_symbol("OrderRepo", "class")]
        results = _detect_repository(syms)
        assert len(results) == 1

    def test_ordinary_class_not_repository(self):
        syms = [make_symbol("UserService", "class")]
        results = _detect_repository(syms)
        assert len(results) == 0

    def test_non_class_ignored(self):
        syms = [make_symbol("repo_helper", "function")]
        results = _detect_repository(syms)
        assert len(results) == 0


class TestDetectPatternsIntegration:
    def test_returns_list(self):
        results = detect_patterns([], {}, {})
        assert isinstance(results, list)
        assert results == []

    def test_detects_multiple_patterns(self):
        syms = [
            make_symbol("UserRepository", "class"),
            make_symbol("ConfigSingleton", "class"),
            make_symbol("PaymentStrategy", "class"),
            make_symbol("CreditCardPayment", "class", parent_class="PaymentStrategy"),
            make_symbol("PayPalPayment", "class", parent_class="PaymentStrategy"),
        ]
        results = detect_patterns(syms, {}, {})
        pattern_types = {r["pattern"] for r in results}
        assert "Repository" in pattern_types
        assert "Singleton" in pattern_types
        assert "Strategy" in pattern_types

    def test_handles_missing_fields(self):
        syms = [{"name": "Test"}]
        results = detect_patterns(syms, {}, {})
        # Should not crash with missing fields
        assert isinstance(results, list)

    def test_handles_empty_inputs(self):
        assert detect_patterns([], {}, {}) == []
        assert detect_patterns([], {"a": []}, {"b": []}) == []

    def test_handles_none_fields(self):
        syms = [{"name": "Thing", "kind": None, "qualified_name": None}]
        results = detect_patterns(syms, {}, {})
        assert isinstance(results, list)
