"""
Парсинг входных файлов: CSV и TXT.

Используется в двух местах:
  * массовый импорт калибровочных пар (истинное, измеренное);
  * загрузка списка измерений для коррекции (только observed-колонка).
"""

import csv
import re
from pathlib import Path


_NUMBER_RE = re.compile(r"[-+]?\d*\.\d+|[-+]?\d+")


def parse_numbers_from_text(text: str) -> list[float]:
    """Достать все числа из произвольного текста."""
    return [float(x) for x in _NUMBER_RE.findall(text)]


def parse_file(filepath: str) -> list[float]:
    """
    Прочитать одномерный список наблюдений из файла.

    Логика:
      * txt-подобные расширения → берём все числа подряд;
      * csv → ищем колонку observed/measured/value/methylation/y,
        иначе первую колонку с числами.
    """
    p = Path(filepath)
    if not p.exists():
        return []

    if p.suffix.lower() != ".csv":
        return parse_numbers_from_text(p.read_text(encoding="utf-8", errors="ignore"))

    with p.open(newline="", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        if not rows:
            return []

        fields = {name.lower().strip(): name for name in (reader.fieldnames or [])}
        obs_col = _find_column(fields, ["observed", "measured", "value", "methylation", "y"])

        if obs_col:
            return _column_as_floats(rows, obs_col)

        # Не нашли по имени — берём первую колонку, в которой есть числа.
        for field in reader.fieldnames or []:
            nums = _column_as_floats(rows, field)
            if nums:
                return nums
        return []


def parse_pairs(filepath: str) -> list[tuple[float, float]]:
    """
    Прочитать пары (истинное, измеренное) для массового импорта.

    Для CSV ищем именованные колонки; иначе берём две первые числовые.
    Для TXT просто разбираем числа парами по порядку.
    """
    p = Path(filepath)
    if not p.exists():
        return []

    if p.suffix.lower() == ".csv":
        pairs = _parse_csv_pairs(p)
        if pairs:
            return pairs

    nums = parse_numbers_from_text(p.read_text(encoding="utf-8", errors="ignore"))
    return [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]


# === Внутренние помощники ===

def _find_column(fields: dict[str, str], candidates: list[str]) -> str | None:
    for c in candidates:
        if c in fields:
            return fields[c]
    return None


def _column_as_floats(rows: list[dict], col: str) -> list[float]:
    out: list[float] = []
    for r in rows:
        val = r.get(col)
        if val in (None, ""):
            continue
        try:
            out.append(float(val))
        except ValueError:
            pass
    return out


def _parse_csv_pairs(p: Path) -> list[tuple[float, float]]:
    with p.open(newline="", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        if not rows:
            return []

        fields = {name.lower().strip(): name for name in (reader.fieldnames or [])}
        true_col = _find_column(fields, ["true", "actual", "level", "calibration", "x"])
        obs_col = _find_column(fields, ["observed", "measured", "value", "methylation", "y"])

        if true_col and obs_col and true_col != obs_col:
            pairs = []
            for r in rows:
                try:
                    pairs.append((float(r[true_col]), float(r[obs_col])))
                except (TypeError, ValueError):
                    pass
            if pairs:
                return pairs

        # По имени не получилось — берём первые две числовые колонки.
        numeric = [c for c in (reader.fieldnames or []) if _is_numeric_column(rows, c)]
        if len(numeric) >= 2:
            c1, c2 = numeric[0], numeric[1]
            pairs = []
            for r in rows:
                try:
                    pairs.append((float(r[c1]), float(r[c2])))
                except (TypeError, ValueError):
                    pass
            return pairs
        return []


def _is_numeric_column(rows: list[dict], col: str) -> bool:
    valid = total = 0
    for r in rows[:50]:
        val = r.get(col)
        if val in (None, ""):
            continue
        total += 1
        try:
            float(val)
            valid += 1
        except ValueError:
            pass
    return total > 0 and (valid / total) > 0.5
