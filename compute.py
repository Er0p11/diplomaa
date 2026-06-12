"""
Пересчёт усреднений по таблице Calibration и подбор аппроксимаций.

Логика разделена на два шага:
  1. recompute_averages_for_gene — пересчитывает Avg_Calibration по группировке
     калибровочных измерений по CalibrationLevel.
  2. compute_and_store_approximations_for_gene — по усреднённым точкам подбирает
     параметры четырёх моделей и сохраняет их в таблицу Approximation.

Оба шага выполняются строго после изменения исходных данных Calibration.
"""

import json
import logging
import sqlite3

import approx as approxmod


logger = logging.getLogger(__name__)


def recompute_averages_for_gene(db_path: str, gene_id: int) -> tuple[bool, str]:
    """
    Пересчитать Avg_Calibration для одного гена.

    Берём все измерения из Calibration, группируем по эталонному уровню
    CalibrationLevel, считаем среднее ObservedMethylation и число замеров.
    Старые строки усреднений для данного гена удаляются перед вставкой новых.
    """
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT CalibrationLevel,
                   COUNT(*),
                   AVG(ObservedMethylation)
            FROM Calibration
            WHERE GeneID = ?
            GROUP BY CalibrationLevel
            ORDER BY CalibrationLevel;
        """, (gene_id,))
        rows = cur.fetchall()

        cur.execute("DELETE FROM Avg_Calibration WHERE GeneID = ?;", (gene_id,))
        for level, cnt, avg in rows:
            cur.execute("""
                INSERT INTO Avg_Calibration
                    (GeneID, CalibrationLevel, AvgObservedMethylation, CountMeasurements)
                VALUES (?, ?, ?, ?);
            """, (gene_id, float(level), float(avg), int(cnt)))
        conn.commit()
    finally:
        conn.close()

    ok = bool(rows)
    return ok, f"Усреднения пересчитаны для гена {gene_id}: {len(rows)} уровней."


def compute_and_store_approximations_for_gene(db_path: str, gene_id: int) -> tuple[bool, str]:
    """
    Подобрать кубическую, гиперболическую и комбинированную аппроксимации
    по усреднённым точкам, сохранить параметры и метрики в Approximation.

    Если усреднённых точек меньше двух — аппроксимации не строятся.
    Коэффициенты хранятся в виде JSON, чтобы было универсально для функций
    с разным числом параметров.
    """
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT CalibrationLevel, AvgObservedMethylation
            FROM Avg_Calibration
            WHERE GeneID = ?
            ORDER BY CalibrationLevel;
        """, (gene_id,))
        rows = cur.fetchall()
        if len(rows) < 2:
            return False, "Недостаточно усреднённых точек для аппроксимации."

        x = [r[0] for r in rows]
        y = [r[1] for r in rows]
        results = approxmod.fit_approximations(x, y)
        if not results:
            return False, "Подбор параметров не дал результата."

        for res in results:
            cur.execute("DELETE FROM Approximation WHERE GeneID = ? AND FunctionType = ?;",
                        (gene_id, res["type"]))
            cur.execute("""
                INSERT INTO Approximation
                    (GeneID, FunctionType, Coefficients, StdDeviation, RelativeError)
                VALUES (?, ?, ?, ?, ?);
            """, (
                gene_id,
                res["type"],
                json.dumps([float(c) for c in res["coeffs"]]),
                float(res["stddev"]),
                float(res["rel_err"]),
            ))
        conn.commit()
    finally:
        conn.close()

    return True, f"Сохранено {len(results)} аппроксимаций для гена {gene_id}."


def recompute_gene(db_path: str, gene_id: int) -> tuple[bool, str]:
    """Шорткат: усреднения + аппроксимации для одного гена."""
    ok1, msg1 = recompute_averages_for_gene(db_path, gene_id)
    ok2, msg2 = compute_and_store_approximations_for_gene(db_path, gene_id)
    return (ok1 and ok2), f"{msg1} / {msg2}"


def recompute_all_genes(db_path: str) -> tuple[int, int, list[dict]]:
    """Пересчитать всё для всех генов в БД (используется фоновым потоком)."""
    conn = sqlite3.connect(db_path)
    try:
        gene_ids = [r[0] for r in conn.execute("SELECT GeneID FROM Gene;").fetchall()]
    finally:
        conn.close()

    success = 0
    details: list[dict] = []
    for gid in gene_ids:
        ok, msg = recompute_gene(db_path, gid)
        if ok:
            success += 1
        details.append({"gene_id": gid, "ok": ok, "msg": msg})
    return success, len(gene_ids), details
