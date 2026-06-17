"""High cyclomatic complexity for testing."""


def simple_function():
    return 1


def moderate_function(x):
    if x > 0:
        return 1
    elif x < 0:
        return -1
    else:
        return 0


def complex_function(x, y, z):
    result = 0
    if x > 0:
        if y > 0:
            for i in range(x):
                if i % 2 == 0:
                    result += i
                else:
                    result -= i
        elif z > 0:
            while z > 0:
                z -= 1
                if z % 3 == 0:
                    result += 1
    else:
        try:
            result = 1 / (x + 1)
        except ZeroDivisionError:
            result = -1
        finally:
            if result < 0:
                result = 0
    return result
