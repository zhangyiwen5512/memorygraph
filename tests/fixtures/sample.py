"""Sample Python file for extractor testing."""


class Calculator:
    """A simple calculator class."""

    def add(self, a: int, b: int) -> int:
        return a + b

    def multiply(self, a: int, b: int) -> int:
        return a * b


def greet(name: str) -> str:
    """Greet someone by name."""
    return f"Hello, {name}"


def main():
    calc = Calculator()
    result = calc.add(1, 2)
    greeting = greet("world")
    print(greeting)
    print(result)


COUNT: int = 0
