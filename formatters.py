"""
Форматирование чисел и LaTeX-формул для панели метрик.

Числа выводятся в обычной десятичной форме в человеко-читаемом диапазоне,
для очень больших/маленьких применяется научная запись с \\cdot 10^{exp}.
"""

import math
from typing import Iterable


def _strip_trailing(s: str) -> str:
    """Убрать висящие нули после запятой: 1.5000 → 1.5, 2.000 → 2."""
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def format_number_plain(x: float) -> str:
    """Читаемое представление числа для вставки в LaTeX (mathtex)."""
    try:
        if x == 0:
            return "0"
        ax = abs(x)
        if 1e-5 <= ax < 1e6:
            return _strip_trailing(f"{x:.6f}")
        exp = int(math.floor(math.log10(ax)))
        mant = _strip_trailing(f"{x / 10 ** exp:.4f}")
        return f"{mant} \\cdot 10^{{{exp}}}"
    except Exception:
        return str(x)


def formula_mathtex(ftype: str, coeffs: Iterable[float]) -> str:
    """Сформировать LaTeX-строку с подставленными коэффициентами."""
    cs = [float(c) for c in coeffs]

    if "куб" in ftype:
        return _cubic_formula(cs)
    if "гипер" in ftype:
        return _hyperbola_formula(cs)
    if "комб" in ftype:
        return _combined_formula(cs)

    return f"P(x): ({', '.join(format_number_plain(c) for c in cs)})"


# === Сборщики формул ===

def _cubic_formula(coeffs: list[float]) -> str:
    a, b, c, d = _take_n(coeffs, 4)
    parts = []
    if a:
        parts.append(f"{format_number_plain(a)} x^3")
    if b:
        parts.append(f"{format_number_plain(b)} x^2")
    if c:
        parts.append(f"{format_number_plain(c)} x")
    if d:
        parts.append(format_number_plain(d))
    return f"P(x) = {_join(parts)}"


def _hyperbola_formula(coeffs: list[float]) -> str:
    a, b, c = _take_n(coeffs, 3)
    frac = f"\\frac{{{format_number_plain(a)}}}{{x + {format_number_plain(c)}}}"
    return f"P(x) = {_join([frac, format_number_plain(b)])}"


def _combined_formula(coeffs: list[float]) -> str:
    a, b, c, d = _take_n(coeffs, 4)
    frac = f"\\frac{{{format_number_plain(b)}}}{{x + {format_number_plain(c)}}}"
    return f"P(x) = {_join([f'{format_number_plain(a)} x', frac, format_number_plain(d)])}"


def _take_n(coeffs: list[float], n: int) -> list[float]:
    return [coeffs[i] if i < len(coeffs) else 0.0 for i in range(n)]


def _join(parts: list[str]) -> str:
    """Склеить слагаемые так, чтобы вместо «+ -» получалось «- »."""
    if not parts:
        return "0"
    expr = " + ".join(parts)
    return expr.replace("+ -", "- ")
