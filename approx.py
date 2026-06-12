"""
Аппроксимационные функции и метрики качества.

Три модели калибровочной кривой:
  - кубический полином          P(x) = a·x³ + b·x² + c·x + d;
  - гипербола со сдвигом        P(x) = a/(x + c) + b;
  - комбинированная со сдвигом  P(x) = a·x + b/(x + c) + d.

Параметры подбираются методом наименьших квадратов готовыми средствами:
полином — numpy.polyfit, нелинейные модели — scipy.optimize.curve_fit.
Коррекция выполняется по калибровочной кривой функцией numpy.interp.
"""

import json
import logging
from typing import Iterable

import numpy as np
from scipy.optimize import curve_fit


logger = logging.getLogger(__name__)


# === Аппроксимирующие функции ===

def cubic_func(x, a, b, c, d):
    """P(x) = a·x³ + b·x² + c·x + d."""
    return a * x ** 3 + b * x ** 2 + c * x + d


def hyperbola_shifted(x, a, b, c):
    """P(x) = a / (x + c) + b."""
    return a / (x + c) + b


def combined_shifted(x, a, b, c, d):
    """P(x) = a·x + b / (x + c) + d."""
    return a * x + b / (x + c) + d


# === Метрики качества ===

def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[float, float]:
    """Вернуть (СКО, средняя относительная ошибка)."""
    resid = y_true - y_pred
    stddev = float(np.sqrt(np.mean(resid ** 2)))
    denom = np.where(np.abs(y_true) < 1e-9, 1.0, np.abs(y_true))
    rel_err = float(np.mean(np.abs(resid) / denom))
    return stddev, rel_err


# === Подбор параметров (готовые средства МНК) ===

def _safe_curve_fit(func, x, y, p0=None, bounds=(-np.inf, np.inf)):
    """Обёртка над curve_fit: не падает, а возвращает None при неудаче."""
    try:
        popt, _ = curve_fit(func, x, y, p0=p0, bounds=bounds, maxfev=20000)
        return popt
    except Exception as e:
        logger.warning("curve_fit для %s не сошёлся: %s", func.__name__, e)
        return None


def fit_approximations(x: Iterable[float], y: Iterable[float]) -> list[dict]:
    """
    По набору усреднённых точек подобрать параметры всех трёх моделей.

    Возвращает список словарей вида:
        {'type': str, 'coeffs': list[float], 'stddev': float, 'rel_err': float}
    Модели, для которых подбор не удался, в результат не попадают.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(x) < 2:
        return []

    results: list[dict] = []

    # Кубическая — нужно хотя бы 4 точки, иначе система недоопределена.
    if len(x) >= 4:
        try:
            coeffs = np.polyfit(x, y, 3).tolist()
            stddev, rel = compute_metrics(y, cubic_func(x, *coeffs))
            results.append({"type": "кубическая",
                            "coeffs": coeffs, "stddev": stddev, "rel_err": rel})
        except Exception as e:
            logger.warning("polyfit для кубической не сошёлся: %s", e)

    # Нелинейные модели фитим по x >= 0 (там нет полюса гиперболы).
    mask = x >= 0
    if mask.sum() >= 2:
        x0, y0 = x[mask], y[mask]
        mean_x, mean_y = float(np.mean(x0)), float(np.mean(y0))
        max_x = float(np.max(x0))
        amp = float(np.max(y0) - np.min(y0))

        # Гипербола: начальные значения подобраны эмпирически.
        p0 = [amp * (mean_x + 1e-3), mean_y, 1e-3]
        bounds = ([-np.inf, -np.inf, 0.0], [np.inf, np.inf, max_x * 10 + 1.0])
        popt = _safe_curve_fit(hyperbola_shifted, x0, y0, p0=p0, bounds=bounds)
        if popt is not None:
            stddev, rel = compute_metrics(y, hyperbola_shifted(x, *popt))
            results.append({"type": "гипербола_сдвиг",
                            "coeffs": popt.tolist(), "stddev": stddev, "rel_err": rel})

        # Комбинированная.
        p0 = [0.0, amp * (mean_x + 1e-3), 1e-3, mean_y]
        bounds = ([-np.inf, -np.inf, 0.0, -np.inf],
                  [np.inf, np.inf, max_x * 10 + 1.0, np.inf])
        popt = _safe_curve_fit(combined_shifted, x0, y0, p0=p0, bounds=bounds)
        if popt is not None:
            stddev, rel = compute_metrics(y, combined_shifted(x, *popt))
            results.append({"type": "комбинированная_сдвиг",
                            "coeffs": popt.tolist(), "stddev": stddev, "rel_err": rel})

    return results


# === Коррекция: по измеренному значению найти истинное ===

def correct_value(func, coeffs, measured: float,
                  lower: float = 0.0, upper: float = 100.0) -> float:
    """
    По измеренному значению вернуть истинное (коррекция).

    Калибровочную кривую считаем в 500 точках и находим нужное значение
    готовой функцией numpy.interp. Кривая монотонна, поэтому ответ
    единственный; за пределами диапазона numpy.interp берёт значение
    на краю.
    """
    if upper <= lower:
        upper = lower + 1.0

    xs = np.linspace(lower, upper, 500)
    ys = np.asarray(func(xs, *coeffs), dtype=float)

    order = np.argsort(ys)
    return float(np.interp(measured, ys[order], xs[order]))


# === Сериализация коэффициентов ===

def coeffs_to_json(coeffs: Iterable[float]) -> str:
    return json.dumps([float(c) for c in coeffs])


def coeffs_from_json(text: str) -> list[float]:
    try:
        return [float(x) for x in json.loads(text)]
    except Exception:
        return []
