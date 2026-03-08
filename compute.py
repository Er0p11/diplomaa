# compute.py
import sqlite3
import json
import numpy as np
from typing import Tuple, List, Dict

import approx as approxmod
from db import DEFAULT_DB

def recompute_averages_for_gene(db_path: str, gene_id: int) -> Tuple[bool, str]:
    """
    Пересчитать Avg_Calibration для одного гена из Calibration.
    Возвращает (ok, message).
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT CalibrationLevel, COUNT(*) AS cnt, AVG(ObservedMethylation) AS avg_val
        FROM Calibration
        WHERE GeneID = ?
        GROUP BY CalibrationLevel
        ORDER BY CalibrationLevel;
    """, (gene_id,))
    rows = cur.fetchall()
    # удаляем старые усреднения
    cur.execute("DELETE FROM Avg_Calibration WHERE GeneID = ?;", (gene_id,))
    for level, cnt, avg_val in rows:
        cur.execute("""
            INSERT INTO Avg_Calibration (GeneID, CalibrationLevel, AvgObservedMethylation, CountMeasurements)
            VALUES (?, ?, ?, ?);
        """, (gene_id, float(level), float(avg_val), int(cnt)))
    conn.commit()
    conn.close()
    ok = len(rows) >= 1
    return ok, f"Усреднения пересчитаны для гена {gene_id} (найдено {len(rows)} уровней)."

import logging
logger = logging.getLogger(__name__)

def compute_and_store_approximations_for_gene(db_path: str, gene_id: int) -> Tuple[bool, str]:
    """
    По таблице Avg_Calibration для gene_id строит аппроксимации (через approx.fit_approximations)
    и сохраняет результаты в таблицу Approximation (JSON в поле Coefficients).
    Возвращает (ok, message).
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT CalibrationLevel, AvgObservedMethylation FROM Avg_Calibration WHERE GeneID = ? ORDER BY CalibrationLevel;", (gene_id,))
    rows = cur.fetchall()
    if not rows or len(rows) < 2:
        conn.close()
        return False, "Недостаточно усреднённых точек для аппроксимации."
    x = np.array([r[0] for r in rows], dtype=float)
    y = np.array([r[1] for r in rows], dtype=float)

    # use approx.fit_approximations to get candidates
    results = approxmod.fit_approximations(x, y)
    if not results:
        conn.close()
        logger.warning(f"No approximations found for gene {gene_id}")
        return False, "Не удалось получить аппроксимации (fit_approximations вернуло пусто)."

    # delete existing approximations for this gene, then insert new ones (by type)
    for res in results:
        ftype = res.get('type')
        coeffs = res.get('coeffs', [])
        stddev = float(res.get('stddev') or 0.0)
        rel_err = float(res.get('rel_err') or 0.0)
        coeffs_json = json.dumps([float(c) for c in coeffs])
        # replace existing
        cur.execute("DELETE FROM Approximation WHERE GeneID = ? AND FunctionType = ?;", (gene_id, ftype))
        cur.execute("""
            INSERT INTO Approximation (GeneID, FunctionType, Coefficients, StdDeviation, RelativeError)
            VALUES (?, ?, ?, ?, ?);
        """, (gene_id, ftype, coeffs_json, stddev, rel_err))
    conn.commit()
    conn.close()
    return True, f"Построено и сохранено {len(results)} аппроксимаций для гена {gene_id}."

def recompute_all_genes(db_path: str) -> Tuple[int, int, List[Dict]]:
    """
    Пересчитать усреднения и аппроксимации для всех генов в базе.
    Возвращает (n_genes_success, n_genes_total, details_list).
    details_list: [{ 'gene_id': int, 'ok_avg': bool, 'ok_approx': bool, 'msg': str }, ...]
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT GeneID FROM Gene;")
    genes = [r[0] for r in cur.fetchall()]
    conn.close()
    success = 0
    details = []
    for gid in genes:
        ok1, msg1 = recompute_averages_for_gene(db_path, gid)
        ok2, msg2 = compute_and_store_approximations_for_gene(db_path, gid)
        combined_msg = msg1 + " / " + msg2
        if ok1 and ok2:
            success += 1
        details.append({'gene_id': gid, 'ok_avg': ok1, 'ok_approx': ok2, 'msg': combined_msg})
    return success, len(genes), details
