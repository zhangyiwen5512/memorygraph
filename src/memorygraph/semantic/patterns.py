"""Static design pattern detection.

Detects 6 common design patterns via heuristic analysis of symbol names,
structures, and relationships. Detection is conservative-biased (宁可多报).
"""


def detect_patterns(symbols: list[dict], callers: dict, callees: dict) -> list[dict]:
    """Detect design patterns in a set of symbols.

    Args:
        symbols: list of symbol dicts with keys: name, kind, qualified_name,
                 parent_class, signature
        callers: dict of {qualified_name: [caller_names]}
        callees: dict of {qualified_name: [callee_names]}

    Returns:
        list of pattern dicts: {pattern, symbol, confidence, evidence}
    """
    patterns = []
    patterns.extend(_detect_singleton(symbols))
    patterns.extend(_detect_factory(symbols, callees))
    patterns.extend(_detect_observer(symbols, callers, callees))
    patterns.extend(_detect_strategy(symbols))
    patterns.extend(_detect_decorator(symbols))
    patterns.extend(_detect_repository(symbols))
    return patterns


def _detect_singleton(symbols: list[dict]) -> list[dict]:
    """Detect Singleton: class with instance/self-returning method."""
    results = []
    for sym in symbols:
        if sym.get("kind") != "class":
            continue
        name = sym.get("name", "")
        sig = sym.get("signature", "")
        # Heuristic: has _instance attribute or getInstance/get_instance method
        if "_instance" in name.lower() or "singleton" in name.lower():
            results.append({
                "pattern": "Singleton",
                "symbol": sym.get("qualified_name", name),
                "confidence": "medium",
                "evidence": "Class name suggests singleton pattern",
            })
        if sig and ("get_instance" in sig or "getInstance" in sig):
            results.append({
                "pattern": "Singleton",
                "symbol": sym.get("qualified_name", name),
                "confidence": "high",
                "evidence": "Has get_instance/getInstance method",
            })
    return results


def _detect_factory(symbols: list[dict], callees: dict) -> list[dict]:
    """Detect Factory: class named *Factory/*Builder that creates objects."""
    results = []
    for sym in symbols:
        name = sym.get("name", "")
        qn = sym.get("qualified_name", name)
        # Name-based: contains Factory/Builder
        if "factory" in name.lower() or "builder" in name.lower():
            results.append({
                "pattern": "Factory",
                "symbol": qn,
                "confidence": "medium",
                "evidence": "Name contains Factory/Builder",
            })
        # Behavioral: returns same-type objects
        if sym.get("kind") in ("function", "method"):
            sig = sym.get("signature", "")
            if sig and "->" in sig:
                return_type = sig.split("->")[-1].strip().rstrip(":")
                if return_type and return_type != "None":
                    # Heuristic: function returns a class name it creates
                    callee_list = callees.get(qn, [])
                    for c in callee_list:
                        if return_type in c:
                            results.append({
                                "pattern": "Factory",
                                "symbol": qn,
                                "confidence": "low",
                                "evidence": f"Returns {return_type} objects",
                            })
                            break
    return results


def _detect_observer(symbols: list[dict], callers: dict,
                     callees: dict) -> list[dict]:
    """Detect Observer: subscribe/notify pattern."""
    results = []
    observed = set()

    for sym in symbols:
        name = sym.get("name", "")
        qn = sym.get("qualified_name", name)
        name_lower = name.lower()

        # Check for subscribe/add_listener/on_ methods
        if any(kw in name_lower for kw in ("subscribe", "add_listener",
                "on_", "register", "attach")):
            observed.add(qn)
            results.append({
                "pattern": "Observer",
                "symbol": qn,
                "confidence": "low",
                "evidence": "Has subscription/registration method",
            })

        # Check for notify/emit/trigger methods
        if any(kw in name_lower for kw in ("notify", "emit", "trigger",
                "dispatch", "fire")):
            results.append({
                "pattern": "Observer",
                "symbol": qn,
                "confidence": "medium",
                "evidence": "Has notification/event method",
            })

    return results


def _detect_strategy(symbols: list[dict]) -> list[dict]:
    """Detect Strategy: abstract base + multiple implementations."""
    results = []
    classes = [s for s in symbols if s.get("kind") == "class"]
    parent_to_children: dict[str, list] = {}

    for cls in classes:
        parent = cls.get("parent_class")
        if parent:
            if parent not in parent_to_children:
                parent_to_children[parent] = []
            parent_to_children[parent].append(cls.get("qualified_name", cls.get("name", "")))

    for parent, children in parent_to_children.items():
        if len(children) >= 2:
            results.append({
                "pattern": "Strategy",
                "symbol": parent,
                "confidence": "medium",
                "evidence": f"Abstract base with {len(children)} implementations: {', '.join(children[:3])}",
            })

    return results


def _detect_decorator(symbols: list[dict]) -> list[dict]:
    """Detect Decorator: class wrapping same-interface object with extra behavior."""
    results = []
    for sym in symbols:
        if sym.get("kind") != "class":
            continue
        name = sym.get("name", "")
        qn = sym.get("qualified_name", name)
        if "decorator" in name.lower() or "wrapper" in name.lower():
            results.append({
                "pattern": "Decorator",
                "symbol": qn,
                "confidence": "medium",
                "evidence": "Name contains Decorator/Wrapper",
            })
        # Heuristic: has __init__ with parameter of same type name
        sig = sym.get("signature", "")
        if sig and "self" in sig:
            # Check if constructor takes a component/wrapped object
            for keyword in ("component", "wrapped", "wrappee", "delegate"):
                if keyword in sig.lower():
                    results.append({
                        "pattern": "Decorator",
                        "symbol": qn,
                        "confidence": "low",
                        "evidence": f"Constructor takes {keyword} parameter",
                    })
                    break
    return results


def _detect_repository(symbols: list[dict]) -> list[dict]:
    """Detect Repository: class with get/find/save/delete CRUD methods."""
    results = []

    for sym in symbols:
        if sym.get("kind") != "class":
            continue
        name = sym.get("name", "")
        qn = sym.get("qualified_name", name)
        name_lower = name.lower()

        # Name-based heuristic
        if any(kw in name_lower for kw in ("repository", "store", "dao", "repo")):
            results.append({
                "pattern": "Repository",
                "symbol": qn,
                "confidence": "high",
                "evidence": "Name contains Repository/Store/DAO",
            })
            continue

    return results
