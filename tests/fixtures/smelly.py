"""Intentional code smells for testing."""


class GodClass:
    """This class does way too many things."""
    def method1(self): pass
    def method2(self): pass
    def method3(self): pass
    def method4(self): pass
    def method5(self): pass
    def method6(self): pass
    def method7(self): pass
    def method8(self): pass
    def method9(self): pass
    def method10(self): pass
    def method11(self): pass
    def method12(self): pass
    def method13(self): pass
    def method14(self): pass
    def method15(self): pass
    def method16(self): pass
    def method17(self): pass
    def method18(self): pass
    def method19(self): pass
    def method20(self): pass
    def method21(self): pass
    def method22(self): pass


def long_method():
    """This method is too long."""
    a = 1
    a += 1; a += 1; a += 1; a += 1; a += 1; a += 1; a += 1; a += 1
    a += 1; a += 1; a += 1; a += 1; a += 1; a += 1; a += 1; a += 1
    a += 1; a += 1; a += 1; a += 1; a += 1; a += 1; a += 1; a += 1
    a += 1; a += 1; a += 1; a += 1; a += 1; a += 1; a += 1; a += 1
    a += 1; a += 1; a += 1; a += 1; a += 1; a += 1; a += 1; a += 1
    a += 1; a += 1; a += 1; a += 1; a += 1; a += 1; a += 1; a += 1
    a += 1; a += 1; a += 1; a += 1; a += 1; a += 1; a += 1; a += 1
    return a


def many_params(a, b, c, d, e, f, g, h):
    """Too many parameters."""
    return a + b + c + d + e + f + g + h


def deeply_nested(x):
    """Deeply nested control flow."""
    return bool(x > 0 and x > 1 and x > 2 and x > 3 and x > 4)


def _dead_code():
    """This private function is never called."""
    pass
