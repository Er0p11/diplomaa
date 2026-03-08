import sqlite3
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox, QMessageBox,
    QTableView, QFileDialog, QTextEdit, QHeaderView, QSplitter,
    QTableWidget, QTableWidgetItem, QInputDialog, QDialog, QFormLayout,
    QDoubleSpinBox, QDialogButtonBox, QLineEdit
)
from PySide6.QtSql import QSqlTableModel, QSqlDatabase, QSqlRecord
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtCore import Qt

import db as dbmod
import approx as approxmod
import utils
import resources
import compute
from formatters import formula_mathtex

plt.rcParams['mathtext.fontset'] = 'stix'
plt.rcParams['font.size'] = 10

def ensure_qsql_connection(connection_name="methyl_conn"):
    if QSqlDatabase.contains(connection_name):
        return QSqlDatabase.database(connection_name)
    for name in QSqlDatabase.connectionNames():
        return QSqlDatabase.database(name)
    return None

class AddPointDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Добавить точку")
        layout = QFormLayout(self)
        
        self.spin_true = QDoubleSpinBox()
        self.spin_true.setRange(0, 100)
        self.spin_true.setDecimals(2)
        
        self.spin_obs = QDoubleSpinBox()
        self.spin_obs.setRange(0, 100)
        self.spin_obs.setDecimals(2)
        
        layout.addRow("Истинное (%):", self.spin_true)
        layout.addRow("Измеренное (%):", self.spin_obs)
        
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def get_values(self):
        return self.spin_true.value(), self.spin_obs.value()

class GenericAddRowDialog(QDialog):
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Добавить запись")
        self.layout = QFormLayout(self)
        self.inputs = {}
        
        record = model.record()
        for i in range(record.count()):
            field_name = record.fieldName(i)
            # Skip likely AutoIncrement IDs (usually first column ending in ID)
            if i == 0 and field_name.endswith("ID"):
                continue
                
            label = resources.COLUMN_NAMES_RU.get(field_name, field_name)
            edit = QLineEdit()
            self.layout.addRow(label + ":", edit)
            self.inputs[i] = edit
            
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        self.layout.addRow(btns)

    def fill_record(self, record):
        for i, edit in self.inputs.items():
            val = edit.text().strip()
            if val:
                record.setValue(i, val)
        return record

class CalibrationWorkspace(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        
        # Top: Gene Selection
        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("Ген:"))
        self.combo_gene = QComboBox()
        self.combo_gene.currentIndexChanged.connect(self.on_gene_changed)
        top_layout.addWidget(self.combo_gene, stretch=1)
        
        self.btn_new_gene = QPushButton("Новый ген")
        self.btn_new_gene.clicked.connect(self.add_new_gene)
        top_layout.addWidget(self.btn_new_gene)
        
        top_layout.addSpacing(20)
        top_layout.addWidget(QLabel("Отображать:"))
        self.combo_display = QComboBox()
        self.combo_display.addItems(["Все аппроксимации", "Кубическая", "Гипербола", "Комбинированная", "Линейная"])
        self.combo_display.currentIndexChanged.connect(self.update_graph_and_results)
        top_layout.addWidget(self.combo_display)
        
        self.btn_export_graph = QPushButton("Экспорт графика")
        self.btn_export_graph.setToolTip("Сохранить текущий график как изображение (PNG, JPG, PDF)")
        self.btn_export_graph.clicked.connect(self.export_graph)
        top_layout.addWidget(self.btn_export_graph)
        
        self.layout.addLayout(top_layout)
        
        # Splitter
        self.splitter = QSplitter(Qt.Horizontal)
        self.layout.addWidget(self.splitter)
        
        # Left: Data Table
        self.left_panel = QWidget()
        self.left_layout = QVBoxLayout(self.left_panel)
        self.left_layout.setContentsMargins(0,0,0,0)
        
        toolbar = QHBoxLayout()
        self.btn_add_pt = QPushButton("Добавить точку")
        self.btn_add_pt.clicked.connect(self.add_point)
        self.btn_del_pt = QPushButton("Удалить")
        self.btn_del_pt.clicked.connect(self.delete_point)
        self.btn_import = QPushButton("Импорт CSV")
        self.btn_import.clicked.connect(self.import_csv)
        toolbar.addWidget(self.btn_add_pt)
        toolbar.addWidget(self.btn_del_pt)
        toolbar.addWidget(self.btn_import)
        self.left_layout.addLayout(toolbar)
        
        self.table_view = QTableView()
        self.table_view.setSelectionBehavior(QTableView.SelectRows)
        self.table_view.setAlternatingRowColors(True)
        self.left_layout.addWidget(self.table_view)
        
        # Shortcuts
        self.shortcut_del = QShortcut(QKeySequence(Qt.Key_Delete), self.table_view)
        self.shortcut_del.activated.connect(self.delete_point)
        
        self.splitter.addWidget(self.left_panel)
        
        # Right: Graph and Results
        self.right_panel = QWidget()
        self.right_layout = QVBoxLayout(self.right_panel)
        self.right_layout.setContentsMargins(0,0,0,0)
        
        self.fig, self.ax = plt.subplots(figsize=(5, 3.5))
        self.canvas = FigureCanvas(self.fig)
        self.right_layout.addWidget(self.canvas, stretch=2)
        
        self.fig_res, self.ax_res = plt.subplots(figsize=(5, 2))
        self.ax_res.axis('off')
        self.canvas_res = FigureCanvas(self.fig_res)
        self.right_layout.addWidget(self.canvas_res, stretch=1)
        
        self.splitter.addWidget(self.right_panel)
        self.splitter.setSizes([400, 600])
        
        self.model = None
        self.refresh_genes()

    def refresh_genes(self, select_id=None):
        self.combo_gene.blockSignals(True)
        self.combo_gene.clear()
        db_path = getattr(dbmod, 'DEFAULT_DB', None)
        if not db_path: 
            self.combo_gene.blockSignals(False)
            return
        rows = dbmod.fetchall("SELECT GeneID, Name FROM Gene ORDER BY GeneID;", (), db_path)
        idx_to_select = 0
        for i, (gid, name) in enumerate(rows):
            self.combo_gene.addItem(f"{name} (ID: {gid})", userData=gid)
            if select_id is not None and gid == select_id:
                idx_to_select = i
        self.combo_gene.blockSignals(False)
        if rows:
            self.combo_gene.setCurrentIndex(idx_to_select)
            self.on_gene_changed()

    def add_new_gene(self):
        name, ok = QInputDialog.getText(self, "Новый ген", "Введите название гена:")
        if ok and name.strip():
            db_path = getattr(dbmod, 'DEFAULT_DB', None)
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("INSERT INTO Gene (Name, Description) VALUES (?, ?)", (name.strip(), ""))
            new_id = cur.lastrowid
            conn.commit()
            conn.close()
            self.refresh_genes(select_id=new_id)

    def current_gene_id(self):
        return self.combo_gene.currentData()

    def on_gene_changed(self):
        gid = self.current_gene_id()
        if gid is None:
            if self.model:
                self.model.clear()
            self.ax.clear()
            self.canvas.draw()
            self.ax_res.clear()
            self.ax_res.axis('off')
            self.canvas_res.draw()
            return
            
        qdb = ensure_qsql_connection()
        if not qdb: return
        
        self.model = QSqlTableModel(self, qdb)
        self.model.setTable("Calibration")
        self.model.setFilter(f"GeneID = {gid}")
        self.model.setEditStrategy(QSqlTableModel.OnFieldChange)
        self.model.select()
        
        self.model.dataChanged.connect(self.on_data_changed)
        
        self.table_view.setModel(self.model)
        
        # Hide unnecessary columns
        idx_gene = self.model.fieldIndex("GeneID")
        idx_calib = self.model.fieldIndex("CalibrationID")
        self.table_view.hideColumn(idx_gene)
        self.table_view.hideColumn(idx_calib)
        
        # Translate column headers
        for i in range(self.model.columnCount()):
            col_name = self.model.record().fieldName(i)
            localized_name = resources.COLUMN_NAMES_RU.get(col_name, col_name)
            if col_name == "CalibrationLevel":
                localized_name = "Истинное (%)"
            elif col_name == "ObservedMethylation":
                localized_name = "Измеренное (%)"
            self.model.setHeaderData(i, Qt.Horizontal, localized_name)
        
        self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        
        self.update_graph_and_results()

    def on_data_changed(self, topLeft, bottomRight, roles):
        # Validate data
        for row in range(topLeft.row(), bottomRight.row() + 1):
            for col in range(topLeft.column(), bottomRight.column() + 1):
                idx = self.model.index(row, col)
                val = self.model.data(idx)
                if val is not None and str(val).strip() != "":
                    try:
                        fval = float(val)
                        if fval < 0 or fval > 100:
                            self.model.blockSignals(True)
                            self.model.setData(idx, 0.0)
                            self.model.blockSignals(False)
                            QMessageBox.warning(self, "Ошибка", f"Значение должно быть от 0 до 100. Введено: {val}")
                    except ValueError:
                        self.model.blockSignals(True)
                        self.model.setData(idx, 0.0)
                        self.model.blockSignals(False)
                        QMessageBox.warning(self, "Ошибка", f"Недопустимое значение: {val}")
        self.calculate_approximations()

    def add_point(self):
        gid = self.current_gene_id()
        if gid is None: return
        
        dialog = AddPointDialog(self)
        if dialog.exec():
            true_val, obs_val = dialog.get_values()
            
            r = self.model.rowCount()
            self.model.insertRow(r)
            self.model.setData(self.model.index(r, self.model.fieldIndex("GeneID")), gid)
            self.model.setData(self.model.index(r, self.model.fieldIndex("CalibrationLevel")), true_val)
            self.model.setData(self.model.index(r, self.model.fieldIndex("ObservedMethylation")), obs_val)
            self.model.submitAll()
            self.calculate_approximations()

    def delete_point(self):
        sel = self.table_view.selectionModel().selectedRows()
        if not sel:
            indexes = self.table_view.selectionModel().selectedIndexes()
            if not indexes: return
            rows = set(idx.row() for idx in indexes)
        else:
            rows = set(idx.row() for idx in sel)
            
        for r in sorted(rows, reverse=True):
            self.model.removeRow(r)
        self.model.submitAll()
        self.model.select()
        self.calculate_approximations()

    def import_csv(self):
        gid = self.current_gene_id()
        if gid is None: return
        path, _ = QFileDialog.getOpenFileName(self, "Импорт CSV", filter="CSV/TXT (*.csv *.txt);;All (*)")
        if not path: return
        pairs = utils.parse_pairs(path)
        if not pairs:
            QMessageBox.warning(self, "Ошибка", "Не удалось найти пары чисел в файле.")
            return
            
        valid_pairs = []
        for t, o in pairs:
            try:
                ft, fo = float(t), float(o)
                if 0 <= ft <= 100 and 0 <= fo <= 100:
                    valid_pairs.append((ft, fo))
            except ValueError:
                pass
                
        if not valid_pairs:
            QMessageBox.warning(self, "Ошибка", "В файле нет валидных пар чисел (от 0 до 100).")
            return
            
        db_path = getattr(dbmod, 'DEFAULT_DB', None)
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        try:
            conn.execute("BEGIN")
            for t, o in valid_pairs:
                cur.execute("INSERT INTO Calibration (GeneID, CalibrationLevel, ObservedMethylation) VALUES (?, ?, ?)", (gid, t, o))
            conn.commit()
            if len(valid_pairs) < len(pairs):
                QMessageBox.information(self, "Успех", f"Импортировано {len(valid_pairs)} точек. {len(pairs) - len(valid_pairs)} точек пропущено из-за неверного формата или выхода за пределы [0, 100].")
            else:
                QMessageBox.information(self, "Успех", f"Импортировано {len(valid_pairs)} точек.")
        except Exception as e:
            conn.rollback()
            QMessageBox.warning(self, "Ошибка", str(e))
        finally:
            conn.close()
            
        self.model.select()
        self.calculate_approximations()

    def calculate_approximations(self):
        gid = self.current_gene_id()
        if gid is None: return
        db_path = getattr(dbmod, 'DEFAULT_DB', None)
        
        # 1. Recompute averages
        ok1, msg1 = compute.recompute_averages_for_gene(db_path, gid)
        # 2. Recompute approximations
        ok2, msg2 = compute.compute_and_store_approximations_for_gene(db_path, gid)
        
        if not (ok1 and ok2):
            # We don't want to spam warnings on every edit, so just log it or show it silently
            print(f"Warning during auto-calc: {msg1} | {msg2}")
            
        self.update_graph_and_results()

    def export_graph(self):
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт графика", filter="PNG Image (*.png);;JPEG Image (*.jpg);;PDF Document (*.pdf)")
        if path:
            self.fig.savefig(path, dpi=300, bbox_inches='tight')
            QMessageBox.information(self, "Успех", f"График сохранен в {path}")

    def update_graph_and_results(self):
        gid = self.current_gene_id()
        if gid is None: return
        db_path = getattr(dbmod, 'DEFAULT_DB', None)
        
        self.ax.clear()
        self.ax_res.clear()
        self.ax_res.axis('off')
        
        # Raw points
        raw_rows = dbmod.fetchall("SELECT CalibrationLevel, ObservedMethylation FROM Calibration WHERE GeneID = ?;", (gid,), db_path)
        if raw_rows:
            rx = [r[0] for r in raw_rows]
            ry = [r[1] for r in raw_rows]
            self.ax.scatter(rx, ry, color='gray', alpha=0.4, s=15, label="Исходные")
            
        # Avg points
        avg_rows = dbmod.fetchall("SELECT CalibrationLevel, AvgObservedMethylation FROM Avg_Calibration WHERE GeneID = ? ORDER BY CalibrationLevel;", (gid,), db_path)
        if avg_rows:
            ax_vals = [r[0] for r in avg_rows]
            ay_vals = [r[1] for r in avg_rows]
            self.ax.scatter(ax_vals, ay_vals, color='blue', s=30, label="Усреднённые", zorder=5)
            
        # Approximations
        approx_rows = dbmod.fetchall("SELECT FunctionType, Coefficients, StdDeviation, RelativeError FROM Approximation WHERE GeneID = ?;", (gid,), db_path)
        
        display_choice = self.combo_display.currentText()
        
        # Prepare data for rendering
        render_items = []
        
        if approx_rows:
            xx = np.linspace(0, 100, 500)
            for ftype, coeffs_text, stddev, rel_err in approx_rows:
                disp = resources.APPROX_DISPLAY.get(ftype, ftype)
                
                # Filter by display choice
                if display_choice != "Все аппроксимации" and display_choice.lower() not in disp.lower():
                    continue
                    
                coeffs = approxmod.coeffs_from_json(coeffs_text)
                
                yy = None
                if 'куб' in ftype and len(coeffs) >= 4:
                    yy = approxmod.cubic_func(xx, *coeffs)
                elif 'гипер' in ftype and len(coeffs) >= 3:
                    xx2 = np.where(xx == 0, 1e-6, xx)
                    yy = approxmod.hyperbola_shifted(xx2, *coeffs)
                elif 'комб' in ftype and len(coeffs) >= 4:
                    xx2 = np.where(xx == 0, 1e-6, xx)
                    yy = approxmod.combined_shifted(xx2, *coeffs)
                elif 'лин' in ftype and len(coeffs) >= 2:
                    yy = approxmod.linear_func(xx, *coeffs)
                    
                if yy is not None:
                    self.ax.plot(xx, yy, label=f"{disp}", linewidth=2)
                    
                latex_formula = formula_mathtex(ftype, coeffs)
                render_items.append({
                    "title": disp,
                    "formula": latex_formula,
                    "sigma": stddev,
                    "rel_err": rel_err
                })
        else:
            self.ax_res.text(0.5, 0.5, "Аппроксимации не рассчитаны.\nДобавьте точки для автоматического расчета.", 
                             ha='center', va='center', fontsize=10)
            
        self.ax.set_xlim(0, 100)
        self.ax.set_ylim(0, 100)
        self.ax.margins(0)
        self.ax.set_xlabel("Истинное метилирование (%)")
        self.ax.set_ylabel("Измеренное метилирование (%)")
        self.ax.grid(True, linestyle='--', alpha=0.7)
        if raw_rows or avg_rows or approx_rows:
            self.ax.legend(fontsize=8, loc='upper left')
            
        self.fig.tight_layout()
        self.canvas.draw()
        
        # Render LaTeX in ax_res
        if render_items:
            y_pos = 0.90
            for item in render_items:
                # Title
                self.ax_res.text(0.01, y_pos, item["title"], fontsize=10, fontweight='bold', va='top', color='#333')
                
                # Formula
                self.ax_res.text(0.01, y_pos - 0.12, f"${item['formula']}$", fontsize=11, va='top')
                
                # Metrics on the right
                metrics_text = f"$\\sigma={item['sigma']:.4f}$\n$\\epsilon={item['rel_err']:.4f}$"
                self.ax_res.text(0.99, y_pos, metrics_text, fontsize=9, va='top', ha='right', color='#555')
                
                y_pos -= 0.25
                
            self.ax_res.set_ylim(min(0, y_pos), 1.0)
            
        self.canvas_res.draw()


class CorrectionWorkspace(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        
        # Top: Gene & Curve Selection
        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("Ген:"))
        self.combo_gene = QComboBox()
        self.combo_gene.currentIndexChanged.connect(self.on_gene_changed)
        top_layout.addWidget(self.combo_gene, stretch=1)
        
        top_layout.addSpacing(20)
        top_layout.addWidget(QLabel("Модель аппроксимации:"))
        self.combo_approx = QComboBox()
        top_layout.addWidget(self.combo_approx, stretch=1)
        
        self.layout.addLayout(top_layout)
        
        # Splitter
        self.splitter = QSplitter(Qt.Horizontal)
        self.layout.addWidget(self.splitter)
        
        # Left: Input
        self.left_panel = QWidget()
        self.left_layout = QVBoxLayout(self.left_panel)
        self.left_layout.setContentsMargins(0,0,0,0)
        
        self.left_layout.addWidget(QLabel("Вставьте измеренные значения (по одному в строке):"))
        self.text_input = QTextEdit()
        # Pre-fill with example values so it's immediately obvious
        self.text_input.setPlainText("10.5\n20.1\n35.0")
        self.left_layout.addWidget(self.text_input)
        
        # Add a small hint label
        lbl_hint = QLabel("<i>(Введите ваши данные вместо примера)</i>")
        lbl_hint.setStyleSheet("color: gray; font-size: 10px;")
        self.left_layout.addWidget(lbl_hint)
        
        toolbar = QHBoxLayout()
        btn_load = QPushButton("Загрузить из файла")
        btn_load.clicked.connect(self.load_file)
        toolbar.addWidget(btn_load)
        
        btn_clear = QPushButton("Очистить")
        btn_clear.clicked.connect(self.text_input.clear)
        toolbar.addWidget(btn_clear)
        self.left_layout.addLayout(toolbar)
        
        self.btn_calc = QPushButton("Рассчитать истинные значения")
        self.btn_calc.setStyleSheet("font-weight: bold; padding: 10px; background-color: #4CAF50; color: white; border-radius: 4px;")
        self.btn_calc.clicked.connect(self.calculate)
        self.left_layout.addWidget(self.btn_calc)
        
        self.splitter.addWidget(self.left_panel)
        
        # Right: Output
        self.right_panel = QWidget()
        self.right_layout = QVBoxLayout(self.right_panel)
        self.right_layout.setContentsMargins(0,0,0,0)
        
        # Graph (New)
        self.fig_corr, self.ax_corr = plt.subplots(figsize=(4, 3))
        self.canvas_corr = FigureCanvas(self.fig_corr)
        self.right_layout.addWidget(self.canvas_corr, stretch=4)
        
        self.right_layout.addWidget(QLabel("Результат коррекции:"))
        self.table_output = QTableWidget()
        self.table_output.setColumnCount(2)
        self.table_output.setHorizontalHeaderLabels(["Измеренное (%)", "Скорректированное (%)"])
        self.table_output.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_output.setAlternatingRowColors(True)
        self.table_output.setEditTriggers(QTableWidget.NoEditTriggers)
        self.right_layout.addWidget(self.table_output, stretch=3)
        
        self.btn_export = QPushButton("Экспорт в CSV")
        self.btn_export.clicked.connect(self.export_csv)
        self.right_layout.addWidget(self.btn_export)
        
        self.splitter.addWidget(self.right_panel)
        self.splitter.setSizes([300, 500])
        
        self.refresh_genes()

    def refresh_genes(self):
        self.combo_gene.blockSignals(True)
        self.combo_gene.clear()
        db_path = getattr(dbmod, 'DEFAULT_DB', None)
        if not db_path: 
            self.combo_gene.blockSignals(False)
            return
        rows = dbmod.fetchall("SELECT GeneID, Name FROM Gene ORDER BY GeneID;", (), db_path)
        for gid, name in rows:
            self.combo_gene.addItem(f"{name} (ID: {gid})", userData=gid)
        self.combo_gene.blockSignals(False)
        if rows:
            self.on_gene_changed()

    def on_gene_changed(self):
        gid = self.combo_gene.currentData()
        self.combo_approx.clear()
        if gid is None: return
        
        db_path = getattr(dbmod, 'DEFAULT_DB', None)
        rows = dbmod.fetchall("SELECT FunctionType, Coefficients FROM Approximation WHERE GeneID = ? ORDER BY ApproximationID;", (gid,), db_path)
        for ft, coeffs in rows:
            disp = resources.APPROX_DISPLAY.get(ft, ft)
            self.combo_approx.addItem(disp, userData=(ft, coeffs))
            
        self.update_chart()
        # Disconnect previous connections to avoid multiple calls
        try:
            self.combo_approx.currentIndexChanged.disconnect(self.update_chart)
        except RuntimeError:
            pass
        self.combo_approx.currentIndexChanged.connect(lambda idx: self.update_chart())

    def load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Открыть файл", filter="Text/CSV (*.txt *.csv);;All (*)")
        if not path: return
        arr = utils.parse_file(path)
        self.text_input.setPlainText("\n".join(str(x) for x in arr))

    def update_chart(self, points=None):
        # Ensure points is not an integer (signal index)
        if isinstance(points, int):
            points = None
            
        self.ax_corr.clear()
        self.ax_corr.set_xlim(0, 100)
        self.ax_corr.set_ylim(0, 100)
        self.ax_corr.set_xlabel("Истинное метилирование (%)")
        self.ax_corr.set_ylabel("Измеренное метилирование (%)")
        self.ax_corr.set_title("Кривая коррекции")
        self.ax_corr.grid(True, linestyle='--', alpha=0.6)
        
        gid = self.combo_gene.currentData()
        approx_data = self.combo_approx.currentData()
        
        if gid is not None and approx_data is not None:
            ftype, coeffs_json = approx_data
            coeffs = approxmod.coeffs_from_json(coeffs_json)
            
            xx = np.linspace(0, 100, 500)
            yy_curve = None
            
            if 'куб' in ftype:
                 yy_curve = approxmod.cubic_func(xx, *coeffs)
            elif 'гипер' in ftype:
                 xx2 = np.where(xx == 0, 1e-6, xx)
                 yy_curve = approxmod.hyperbola_shifted(xx2, *coeffs)
            elif 'комб' in ftype:
                 xx2 = np.where(xx == 0, 1e-6, xx)
                 yy_curve = approxmod.combined_shifted(xx2, *coeffs)
            elif 'лин' in ftype:
                 yy_curve = approxmod.linear_func(xx, *coeffs)
                 
            if yy_curve is not None:
                disp = resources.APPROX_DISPLAY.get(ftype, ftype)
                self.ax_corr.plot(xx, yy_curve, 'b-', alpha=0.6, label=f"{disp}")
        
        if points and isinstance(points, (list, tuple)) and len(points) == 2:
            x_vals, y_vals = points
            self.ax_corr.scatter(x_vals, y_vals, color='red', s=25, label='Скорректированные', zorder=5)
            
        if (gid is not None and approx_data is not None) or points:
            self.ax_corr.legend(fontsize=8)
            
        self.canvas_corr.draw()

    def calculate(self):
        gid = self.combo_gene.currentData()
        approx_data = self.combo_approx.currentData()
        
        if gid is None or approx_data is None:
            QMessageBox.warning(self, "Ошибка", "Выберите ген и модель аппроксимации.")
            return
            
        ftype, coeffs_json = approx_data
        coeffs = approxmod.coeffs_from_json(coeffs_json)
        
        if 'куб' in ftype:
            func = approxmod.cubic_func; lower = 0.0
        elif 'гипер' in ftype:
            func = approxmod.hyperbola_shifted; lower = 1e-6
        elif 'комб' in ftype:
            func = approxmod.combined_shifted; lower = 1e-6
        elif 'лин' in ftype:
            func = approxmod.linear_func; lower = 0.0
        else:
            QMessageBox.warning(self, "Ошибка", "Неизвестный тип аппроксимации.")
            return
            
        text = self.text_input.toPlainText()
        nums = utils.parse_numbers_from_text(text)
        
        valid_nums = []
        for n in nums:
            if 0 <= n <= 100:
                valid_nums.append(n)
        
        if not valid_nums:
            QMessageBox.warning(self, "Ошибка", "Нет валидных данных для расчета (значения должны быть от 0 до 100).")
            return
            
        if len(valid_nums) < len(nums):
            QMessageBox.warning(self, "Предупреждение", f"Пропущено {len(nums) - len(valid_nums)} значений, выходящих за пределы [0, 100].")
            
        self.table_output.setRowCount(len(valid_nums))
        
        db_path = getattr(dbmod, 'DEFAULT_DB', None)
        rows_cal = dbmod.fetchall("SELECT MAX(CalibrationLevel) FROM Avg_Calibration WHERE GeneID = ?;", (gid,), db_path)
        max_cal = float(rows_cal[0][0]) if rows_cal and rows_cal[0][0] is not None else 100.0
        upper = max(100.0, max_cal * 1.2)
        
        x_vals = []
        y_vals = []
        
        for i, y in enumerate(valid_nums):
            x = approxmod.invert_value(func, coeffs, y, lower=lower, upper=upper)
            
            item_y = QTableWidgetItem(f"{y:.4f}")
            item_x = QTableWidgetItem(f"{x:.4f}" if x is not None else "Ошибка")
            
            self.table_output.setItem(i, 0, item_y)
            self.table_output.setItem(i, 1, item_x)
            
            if x is not None:
                x_vals.append(x)
                y_vals.append(y)
                
        self.update_chart(points=(x_vals, y_vals))

    def export_csv(self):
        if self.table_output.rowCount() == 0: return
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт", filter="CSV (*.csv)")
        if not path: return
        
        import csv
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["Observed", "Corrected"])
            for r in range(self.table_output.rowCount()):
                y = self.table_output.item(r, 0).text()
                x = self.table_output.item(r, 1).text()
                writer.writerow([y, x])
        QMessageBox.information(self, "Успех", "Данные экспортированы.")


class DatabaseEditorWorkspace(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        
        top = QHBoxLayout()
        top.addWidget(QLabel("Таблица:"))
        self.combo = QComboBox()
        
        # Show all tables from the database
        self.combo.currentIndexChanged.connect(self.refresh)
        top.addWidget(self.combo)
        
        btn_add = QPushButton("Добавить запись")
        btn_add.clicked.connect(self.add_row)
        top.addWidget(btn_add)
        
        btn_del = QPushButton("Удалить")
        btn_del.clicked.connect(self.delete_row)
        top.addWidget(btn_del)
        
        self.layout.addLayout(top)
        
        self.view = QTableView()
        self.view.setSelectionBehavior(QTableView.SelectRows)
        self.view.setAlternatingRowColors(True)
        self.layout.addWidget(self.view)
        
        # Shortcuts
        self.shortcut_del = QShortcut(QKeySequence(Qt.Key_Delete), self.view)
        self.shortcut_del.activated.connect(self.delete_row)
        
        self.model = None
        self.refresh_tables()

    def refresh_tables(self):
        self.combo.blockSignals(True)
        self.combo.clear()
        
        qdb = ensure_qsql_connection()
        if qdb and qdb.isOpen():
            tables = qdb.tables()
            # Filter out sqlite internal tables
            tables = [t for t in tables if not t.startswith("sqlite_")]
            for t in tables:
                disp_name = resources.TABLE_LABELS.get(t, t)
                self.combo.addItem(disp_name, userData=t)
        
        self.combo.blockSignals(False)
        if self.combo.count() > 0:
            self.refresh()

    def current_table(self):
        return self.combo.currentData()

    def refresh(self):
        table = self.current_table()
        if not table: return
        
        qdb = ensure_qsql_connection()
        if not qdb: return
        
        self.model = QSqlTableModel(self, qdb)
        self.model.setTable(table)
        self.model.setEditStrategy(QSqlTableModel.OnFieldChange)
        self.model.select()
        
        # Localize column names
        for i in range(self.model.columnCount()):
            col_name = self.model.record().fieldName(i)
            localized_name = resources.COLUMN_NAMES_RU.get(col_name, col_name)
            self.model.setHeaderData(i, Qt.Horizontal, localized_name)
        
        self.view.setModel(self.model)
        self.view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.view.horizontalHeader().setStretchLastSection(True)

    def add_row(self):
        table = self.current_table()
        if not table or not self.model: return
        
        dialog = GenericAddRowDialog(self.model, self)
        if dialog.exec():
            record = self.model.record()
            record = dialog.fill_record(record)
            
            if self.model.insertRecord(-1, record):
                self.model.submitAll()
                self.refresh()
                self.view.scrollToBottom()
            else:
                QMessageBox.warning(self, "Ошибка", "Не удалось добавить запись.\n" + self.model.lastError().text())

    def delete_row(self):
        sel = self.view.selectionModel().selectedRows()
        if not sel:
            indexes = self.view.selectionModel().selectedIndexes()
            if not indexes: return
            rows = set(idx.row() for idx in indexes)
        else:
            rows = set(idx.row() for idx in sel)
            
        for r in sorted(rows, reverse=True):
            self.model.removeRow(r)
        self.model.submitAll()
        self.refresh()

class HelpWorkspace(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.l = QVBoxLayout(self)
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        
        # Use the full help text from resources and render as Markdown
        if hasattr(resources, 'HELP_TEXT_FULL'):
            self.text.setMarkdown(resources.HELP_TEXT_FULL)
        else:
            # Fallback if not found
            self.text.setPlainText(resources.HELP_TEXT_SHORT)
            
        self.l.addWidget(self.text)
