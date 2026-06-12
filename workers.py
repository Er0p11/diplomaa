"""
Фоновые потоки QThread для пересчёта усреднений и аппроксимаций.

Расчёт вынесен из основного потока, чтобы интерфейс не подвисал при крупных
объёмах данных или при пересчёте всех генов сразу.
"""

from PySide6.QtCore import QThread, Signal

import compute


class RecomputeGeneThread(QThread):
    """Пересчёт усреднений и аппроксимаций для одного гена."""

    finished_signal = Signal(bool, str)  # (успех, текст для статус-бара)

    def __init__(self, db_path: str, gene_id: int):
        super().__init__()
        self.db_path = db_path
        self.gene_id = gene_id

    def run(self) -> None:
        try:
            ok, msg = compute.recompute_gene(self.db_path, self.gene_id)
            self.finished_signal.emit(ok, msg)
        except Exception as e:
            self.finished_signal.emit(False, f"Ошибка пересчёта: {e}")


class RecomputeAllThread(QThread):
    """Полный пересчёт по всем генам в базе."""

    finished_signal = Signal(int, int)  # (успешных генов, всего)

    def __init__(self, db_path: str):
        super().__init__()
        self.db_path = db_path

    def run(self) -> None:
        try:
            succ, total, _ = compute.recompute_all_genes(self.db_path)
            self.finished_signal.emit(succ, total)
        except Exception as e:
            self.finished_signal.emit(0, 0)
            raise e
