# workers.py
from PySide6.QtCore import QThread, Signal
import compute

class RecomputeAllThread(QThread):
    # finished_signal emits (success_count, total_count, details_list)
    finished_signal = Signal(int, int, object)
    error_signal = Signal(str)

    def __init__(self, db_path):
        super().__init__()
        self.db_path = db_path

    def run(self):
        try:
            succ, total, details = compute.recompute_all_genes(self.db_path)
            self.finished_signal.emit(succ, total, details)
        except Exception as e:
            self.error_signal.emit(str(e))

class RecomputeGeneThread(QThread):
    finished_signal = Signal(bool, str)  # ok, message
    error_signal = Signal(str)

    def __init__(self, db_path, gene_id):
        super().__init__()
        self.db_path = db_path
        self.gene_id = gene_id

    def run(self):
        try:
            ok1, msg1 = compute.recompute_averages_for_gene(self.db_path, self.gene_id)
            ok2, msg2 = compute.compute_and_store_approximations_for_gene(self.db_path, self.gene_id)
            ok = ok1 and ok2
            message = msg1 + "\n" + msg2
            self.finished_signal.emit(ok, message)
        except Exception as e:
            self.error_signal.emit(str(e))
