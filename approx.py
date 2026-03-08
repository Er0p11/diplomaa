# approx.py
import numpy as np
import json
from scipy.optimize import curve_fit, minimize_scalar

def cubic_func(x, a, b, c, d):
    return a * x**3 + b * x**2 + c * x + d

def hyperbola_shifted(x, a, b, c):
    return a / (x + c) + b

def combined_shifted(x, a, b, c, d):
    return a * x + b / (x + c) + d

def linear_func(x, a, b):
    return a * x + b

import logging
logger = logging.getLogger(__name__)

def safe_curve_fit(func, x, y, p0=None, bounds=(-np.inf, np.inf), maxfev=20000):
    try:
        popt, pcov = curve_fit(func, x, y, p0=p0, bounds=bounds, maxfev=maxfev)
        return popt, pcov, None
    except Exception as e:
        logger.warning(f"Curve fit failed for {func.__name__}: {e}")
        return None, None, str(e)

def compute_metrics(y_true, y_pred):
    resid = y_true - y_pred
    stddev = float(np.sqrt(np.mean(resid**2)))
    denom = np.where(np.abs(y_true) < 1e-9, 1.0, np.abs(y_true))
    rel_err = float(np.mean(np.abs(resid) / denom))
    return stddev, rel_err

def fit_approximations(x, y):
    """
    Возвращает список словарей:
    [{ 'type': 'кубическая', 'coeffs': [...], 'stddev':..., 'rel_err': ... }, ...]
    """
    results = []
    x = np.array(x, dtype=float)
    y = np.array(y, dtype=float)
    if len(x) < 2:
        return results

    # линейная
    if len(x) >= 2:
        try:
            p = np.polyfit(x, y, 1)
            coeffs = p.tolist()
            y_pred = linear_func(x, *coeffs)
            stddev, rel_err = compute_metrics(y, y_pred)
            results.append({'type':'линейная', 'coeffs':coeffs, 'stddev':stddev, 'rel_err':rel_err})
        except Exception:
            popt, pcov, err = safe_curve_fit(linear_func, x, y)
            if popt is not None:
                y_pred = linear_func(x, *popt)
                stddev, rel_err = compute_metrics(y, y_pred)
                results.append({'type':'линейная', 'coeffs':popt.tolist(), 'stddev':stddev, 'rel_err':rel_err})

    # кубическая (если достаточно точек)
    if len(x) >= 4:
        try:
            p = np.polyfit(x, y, 3)
            coeffs = p.tolist()
            y_pred = cubic_func(x, *coeffs)
            stddev, rel_err = compute_metrics(y, y_pred)
            results.append({'type':'кубическая', 'coeffs':coeffs, 'stddev':stddev, 'rel_err':rel_err})
        except Exception:
            popt, pcov, err = safe_curve_fit(cubic_func, x, y)
            if popt is not None:
                y_pred = cubic_func(x, *popt)
                stddev, rel_err = compute_metrics(y, y_pred)
                results.append({'type':'кубическая', 'coeffs':popt.tolist(), 'stddev':stddev, 'rel_err':rel_err})

    # гипербола сдвиг и комбинированная
    mask = x >= 0
    if mask.sum() >= 2:
        x0 = x[mask]; y0 = y[mask]
        # гипербола
        a0 = (max(y0)-min(y0))*(np.mean(x0)+1e-3)
        b0 = np.mean(y0)
        c0 = 1e-3
        p0 = [a0, b0, c0]
        bounds = ([-np.inf, -np.inf, 0.0], [np.inf, np.inf, np.max(x0)*10 + 1.0])
        popt_h, pcov_h, errh = safe_curve_fit(hyperbola_shifted, x0, y0, p0=p0, bounds=bounds)
        if popt_h is not None:
            y_pred = hyperbola_shifted(x, *popt_h)
            stddev, rel_err = compute_metrics(y, y_pred)
            results.append({'type':'гипербола_сдвиг', 'coeffs':popt_h.tolist(), 'stddev':stddev, 'rel_err':rel_err})
        # комбинированная
        p0 = [0.0, (max(y0)-min(y0))*(np.mean(x0)+1e-3), 1e-3, np.mean(y0)]
        bounds = ([-np.inf, -np.inf, 0.0, -np.inf], [np.inf, np.inf, np.max(x0)*10 + 1.0, np.inf])
        popt_c, pcov_c, errc = safe_curve_fit(combined_shifted, x0, y0, p0=p0, bounds=bounds)
        if popt_c is not None:
            y_pred = combined_shifted(x, *popt_c)
            stddev, rel_err = compute_metrics(y, y_pred)
            results.append({'type':'комбинированная_сдвиг', 'coeffs':popt_c.tolist(), 'stddev':stddev, 'rel_err':rel_err})
    return results

def invert_value(func, coeffs, y_target, lower=0.0, upper=None, x_grid_max=100.0):
    """
    Инвертирование функции через minimize_scalar — возвращает x или None.
    upper: если None — поставить x_grid_max
    """
    if upper is None:
        upper = x_grid_max

    def obj(x):
        try:
            val = func(np.array([x]), *coeffs)
            v = float(np.atleast_1d(val)[0])
            return (v - y_target)**2
        except Exception:
            return 1e12

    # ensure lower < upper
    lo = float(lower)
    hi = float(upper)
    if hi <= lo:
        hi = lo + 1.0

    res = minimize_scalar(obj, bounds=(lo, hi), method='bounded', options={'xatol':1e-6})
    if res.success:
        return float(res.x)
    return None

# JSON utilities for storing coeffs
def coeffs_to_json(coeffs):
    return json.dumps([float(c) for c in coeffs])

def coeffs_from_json(text):
    try:
        arr = json.loads(text)
        return [float(x) for x in arr]
    except Exception:
        return []
