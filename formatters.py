# formatters.py
from typing import List
import math

def _strip_trailing(s: str) -> str:
    if '.' in s:
        s = s.rstrip('0').rstrip('.')
    return s

def format_number_plain(x: float) -> str:
    """
    Человеко-читаемое представление числа (без e+06).
    Возвращает либо обычную десятичную запись, либо строку вида 'm \\times 10^{exp}'.
    """
    try:
        if x == 0:
            return "0"
        ax = abs(x)
        # Расширяем диапазон для обычной записи: от 1e-5 до 1e6
        if 1e-5 <= ax < 1e6:
            # Используем достаточно знаков, чтобы не потерять точность, но убираем лишние нули
            s = f"{x:.6f}"
            return _strip_trailing(s)
        
        # Для очень маленьких или очень больших чисел оставляем научную запись,
        # но делаем её чуть более аккуратной
        exp = int(math.floor(math.log10(ax)))
        mant = x / (10 ** exp)
        mant_s = _strip_trailing(f"{mant:.4f}") # Меньше знаков в мантиссе для читаемости
        return f"{mant_s} \\cdot 10^{{{exp}}}"
    except Exception:
        return str(x)

def format_number_for_html(x: float) -> str:
    """Аналог format_number_plain но безопасен для вставки в HTML."""
    s = format_number_plain(x)
    return s.replace(r"\times 10^{", "&times; 10<sup>").replace("}", "</sup>")

def formula_mathtex(ftype: str, coeffs: List[float]) -> str:
    """
    Возвращает LaTeX-строку:
    - кубическая: P(x) = a x^3 + b x^2 + c x + d
    - гипербола: P(x) = a / (x + c) + b
    - комбинированная: P(x) = a x + b / (x + c) + d
    Числа форматируются читабельно.
    """
    try:
        if 'куб' in ftype or 'кубическая' in ftype:
            a, b, c, d = (float(coeffs[i]) if i < len(coeffs) else 0.0 for i in range(4))
            parts = []
            if a != 0:
                parts.append(f"{format_number_plain(a)} x^3")
            if b != 0:
                parts.append(f"{format_number_plain(b)} x^2")
            if c != 0:
                parts.append(f"{format_number_plain(c)} x")
            if d != 0:
                parts.append(f"{format_number_plain(d)}")
            if not parts:
                expr = "0"
            else:
                expr = " + ".join(parts)
                expr = expr.replace("+ -", "- ")
            return f"P(x) = {expr}"
        if 'гипер' in ftype or 'hyper' in ftype:
            a = float(coeffs[0]) if len(coeffs) > 0 else 0.0
            b = float(coeffs[1]) if len(coeffs) > 1 else 0.0
            c = float(coeffs[2]) if len(coeffs) > 2 else 0.0
            denom = f"x + {format_number_plain(c)}"
            frac = f"\\frac{{{format_number_plain(a)}}}{{{denom}}}"
            expr = f"{frac} + {format_number_plain(b)}"
            expr = expr.replace("+ -", "- ")
            return f"P(x) = {expr}"
        if 'комб' in ftype or 'combined' in ftype:
            a = float(coeffs[0]) if len(coeffs) > 0 else 0.0
            b = float(coeffs[1]) if len(coeffs) > 1 else 0.0
            c = float(coeffs[2]) if len(coeffs) > 2 else 0.0
            d = float(coeffs[3]) if len(coeffs) > 3 else 0.0
            denom = f"x + {format_number_plain(c)}"
            frac = f"\\frac{{{format_number_plain(b)}}}{{{denom}}}"
            expr = f"{format_number_plain(a)} x + {frac} + {format_number_plain(d)}"
            expr = expr.replace("+ -", "- ")
            return f"P(x) = {expr}"
        if 'лин' in ftype or 'linear' in ftype:
            a = float(coeffs[0]) if len(coeffs) > 0 else 0.0
            b = float(coeffs[1]) if len(coeffs) > 1 else 0.0
            parts = []
            if a != 0:
                parts.append(f"{format_number_plain(a)} x")
            if b != 0:
                parts.append(f"{format_number_plain(b)}")
            if not parts:
                expr = "0"
            else:
                expr = " + ".join(parts)
                expr = expr.replace("+ -", "- ")
            return f"P(x) = {expr}"
    except Exception:
        pass
    coeffs_s = ", ".join(format_number_plain(c) for c in coeffs)
    return f"P(x): ({coeffs_s})"
