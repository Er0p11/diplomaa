"""
Рабочие вкладки приложения.

Содержимое:
  CalibrationWorkspace     — основная вкладка: ген, исследование, таблица
                             точек и график аппроксимаций;
  CorrectionWorkspace      — коррекция «сырых» значений по выбранной модели;
  ReferenceEditorWorkspace — редактор справочных и сопутствующих данных.

Все вкладки получают callback status_cb для вывода сообщений в статус-бар.
"""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Callable

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QDoubleValidator, QIntValidator, QKeySequence, QShortcut
from PySide6.QtSql import QSqlDatabase, QSqlTableModel
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSplitter, QStyledItemDelegate, QTableView, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)

import approx as approxmod
import db as dbmod
import resources
import utils
from formatters import formula_mathtex
from workers import RecomputeGeneThread


plt.rcParams["mathtext.fontset"] = "stix"
plt.rcParams["font.size"] = 10


StatusFn = Callable[[str], None]
_NOOP: StatusFn = lambda _msg: None

ALL_STUDIES = "Все исследования"


# ============================================================================
# Вспомогательные виджеты и диалоги
# ============================================================================

def _qsql_connection() -> QSqlDatabase | None:
    """Получить открытое соединение QSql (создаётся в main.py)."""
    for name in QSqlDatabase.connectionNames():
        return QSqlDatabase.database(name)
    return None


class PercentageDelegate(QStyledItemDelegate):
    """Редактор-ячейка для процентных значений 0..100."""

    def createEditor(self, parent, option, index):
        editor = QDoubleSpinBox(parent)
        editor.setRange(0.0, 100.0)
        editor.setDecimals(4)
        editor.setSingleStep(0.1)
        return editor


class CopyableTableView(QTableView):
    """QTableView с поддержкой Ctrl+C/Ctrl+V для табличных данных."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionBehavior(QTableView.SelectItems)
        self.setSelectionMode(QTableView.ExtendedSelection)
        self.setAlternatingRowColors(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.horizontalHeader().setStretchLastSection(True)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Copy):
            self._copy_selection()
        elif event.matches(QKeySequence.Paste):
            self._paste_selection()
        else:
            super().keyPressEvent(event)

    def _copy_selection(self) -> None:
        model = self.model()
        sel = self.selectionModel()
        if not (model and sel and sel.hasSelection()):
            return
        indexes = sorted(sel.selectedIndexes(), key=lambda i: (i.row(), i.column()))
        rows: list[list[str]] = []
        current_row, line = indexes[0].row(), []
        for idx in indexes:
            if idx.row() != current_row:
                rows.append(line)
                line = []
                current_row = idx.row()
            val = model.data(idx)
            line.append("" if val is None else str(val))
        rows.append(line)
        QApplication.clipboard().setText("\n".join("\t".join(r) for r in rows))

    def _paste_selection(self) -> None:
        model = self.model()
        sel = self.selectionModel()
        if not (model and sel and sel.hasSelection()):
            return
        text = QApplication.clipboard().text()
        if not text:
            return
        start = sel.selectedIndexes()[0]
        for di, row_text in enumerate(text.splitlines()):
            for dj, cell in enumerate(row_text.split("\t")):
                r, c = start.row() + di, start.column() + dj
                if r < model.rowCount() and c < model.columnCount():
                    model.setData(model.index(r, c), cell.strip())


class AddPointDialog(QDialog):
    """Ручное добавление одной калибровочной точки."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Добавить точку")
        layout = QFormLayout(self)
        self.spin_true = QDoubleSpinBox(decimals=4)
        self.spin_true.setRange(0.0, 100.0)
        self.spin_obs = QDoubleSpinBox(decimals=4)
        self.spin_obs.setRange(0.0, 100.0)
        layout.addRow("Истинное (%):", self.spin_true)
        layout.addRow("Измеренное (%):", self.spin_obs)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def values(self) -> tuple[float, float]:
        return self.spin_true.value(), self.spin_obs.value()


# ============================================================================
# Конфигурация редактора справочных данных
# ============================================================================

F_TEXT = "text"
F_INT = "int"
F_REAL = "real"
F_DATE = "date"
F_FK = "fk"


@dataclass
class RefField:
    db: str
    label: str
    type: str = F_TEXT
    required: bool = False
    fk_table: str = ""
    fk_id: str = ""
    fk_display: str = ""


@dataclass
class RefEntity:
    table: str
    label: str
    pk: str
    fields: list[RefField] = dc_field(default_factory=list)


REFERENCE_ENTITIES: list[RefEntity] = [
    RefEntity("Researchers", "Исследователи", "ResearcherID", [
        RefField("FullName", "ФИО", F_TEXT, required=True),
        RefField("Workplace", "Место работы", F_TEXT),
        RefField("Email", "Электронная почта", F_TEXT),
    ]),
    RefEntity("Publications", "Публикации", "PublicationID", [
        RefField("Title", "Название статьи", F_TEXT, required=True),
        RefField("Journal", "Журнал", F_TEXT),
        RefField("Volume", "Том", F_INT),
        RefField("Year", "Год", F_INT),
        RefField("Pages", "Число страниц", F_INT),
        RefField("ResearcherID", "Автор", F_FK, required=True,
                 fk_table="Researchers", fk_id="ResearcherID",
                 fk_display="FullName"),
    ]),
    RefEntity("Reagents", "Реактивы", "ReagentID", [
        RefField("Name", "Название набора", F_TEXT, required=True),
        RefField("Manufacturer", "Производитель", F_TEXT),
        RefField("Country", "Страна", F_TEXT),
        RefField("CatalogNumber", "Каталожный номер", F_TEXT),
    ]),
    RefEntity("Study", "Исследования", "StudyID", [
        RefField("Title", "Название", F_TEXT, required=True),
        RefField("ResearcherID", "Исследователь", F_FK, required=True,
                 fk_table="Researchers", fk_id="ResearcherID",
                 fk_display="FullName"),
        RefField("PublicationID", "Публикация", F_FK,
                 fk_table="Publications", fk_id="PublicationID",
                 fk_display="Title"),
        RefField("Date", "Дата (ГГГГ-ММ-ДД)", F_DATE),
    ]),
    RefEntity("Primers", "Праймеры", "PrimerID", [
        RefField("GeneID", "Ген", F_FK, required=True,
                 fk_table="Gene", fk_id="GeneID", fk_display="Name"),
        RefField("Sequence", "Последовательность нуклеотидов", F_TEXT,
                 required=True),
        RefField("GeneCopySize", "Размер копии гена", F_INT),
        RefField("CpGPositions", "Число CpG-позиций", F_INT),
    ]),
    RefEntity("AmplificationStep", "Этапы амплификации", "AmplificationID", [
        RefField("GeneID", "Ген", F_FK, required=True,
                 fk_table="Gene", fk_id="GeneID", fk_display="Name"),
        RefField("StepNumber", "Номер шага", F_INT, required=True),
        RefField("Temperature", "Температура (°C)", F_REAL),
        RefField("DurationSeconds", "Длительность (с)", F_INT),
    ]),
]


def _fk_options(field: RefField) -> list[tuple[int, str]]:
    rows = dbmod.fetchall(
        f"SELECT {field.fk_id}, {field.fk_display} "
        f"FROM {field.fk_table} ORDER BY {field.fk_display};"
    )
    return [(r[0], str(r[1]) if r[1] is not None else f"#{r[0]}") for r in rows]


class RecordFormDialog(QDialog):
    """Форма добавления/редактирования одной записи справочника."""

    def __init__(self, entity: RefEntity, values: dict | None = None, parent=None):
        super().__init__(parent)
        self.entity = entity
        self.is_edit = values is not None
        self.setWindowTitle(
            f"{'Изменить' if self.is_edit else 'Добавить'}: {entity.label}"
        )
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        self.widgets: dict[str, QWidget] = {}
        values = values or {}

        for f in entity.fields:
            label = f.label + (" *" if f.required else "")
            if f.type == F_FK:
                w = QComboBox()
                if not f.required:
                    w.addItem("— не указано —", userData=None)
                for fk_id, disp in _fk_options(f):
                    w.addItem(disp, userData=fk_id)
                cur = values.get(f.db)
                if cur is not None:
                    pos = w.findData(cur)
                    if pos >= 0:
                        w.setCurrentIndex(pos)
            else:
                w = QLineEdit()
                if f.type == F_INT:
                    w.setValidator(QIntValidator())
                elif f.type == F_REAL:
                    dv = QDoubleValidator()
                    dv.setNotation(QDoubleValidator.StandardNotation)
                    w.setValidator(dv)
                elif f.type == F_DATE:
                    w.setPlaceholderText("например, 2024-05-17")
                cur = values.get(f.db)
                if cur is not None:
                    w.setText(str(cur))
            form.addRow(label + ":", w)
            self.widgets[f.db] = w

        hint = QLabel("Поля со звёздочкой (*) обязательны для заполнения.")
        hint.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(hint)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("Сохранить")
        btns.button(QDialogButtonBox.Cancel).setText("Отмена")
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _on_accept(self) -> None:
        for f in self.entity.fields:
            if not f.required:
                continue
            w = self.widgets[f.db]
            if isinstance(w, QComboBox):
                if w.currentData() is None:
                    self._warn(f.label)
                    return
            elif not w.text().strip():
                self._warn(f.label)
                return
        self.accept()

    def _warn(self, label: str) -> None:
        QMessageBox.warning(self, "Не заполнено",
                            f"Поле «{label}» обязательно для заполнения.")

    def values(self) -> dict:
        result: dict = {}
        for f in self.entity.fields:
            w = self.widgets[f.db]
            if isinstance(w, QComboBox):
                result[f.db] = w.currentData()
            else:
                text = w.text().strip()
                if not text:
                    result[f.db] = None
                elif f.type == F_INT:
                    result[f.db] = int(text)
                elif f.type == F_REAL:
                    result[f.db] = float(text.replace(",", "."))
                else:
                    result[f.db] = text
        return result


# ============================================================================
# Окно отдельного графика
# ============================================================================

class PlotWindow(QDialog):
    """Самостоятельное окно с графиком и интерактивной панелью matplotlib."""

    def __init__(self, parent=None, title: str = "График"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 650)
        layout = QVBoxLayout(self)
        self.fig, self.ax = plt.subplots(figsize=(8, 6))
        self.canvas = FigureCanvas(self.fig)
        self.toolbar = NavigationToolbar(self.canvas, self)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)

    def render(self, draw_fn: Callable) -> None:
        draw_fn(self.ax)
        self.fig.tight_layout()
        self.canvas.draw()


def _evaluate(ftype: str, coeffs: list[float], xx: np.ndarray) -> np.ndarray | None:
    """Универсальное вычисление модели по типу."""
    if "куб" in ftype and len(coeffs) >= 4:
        return approxmod.cubic_func(xx, *coeffs)
    if "гипер" in ftype and len(coeffs) >= 3:
        return approxmod.hyperbola_shifted(xx, *coeffs)
    if "комб" in ftype and len(coeffs) >= 4:
        return approxmod.combined_shifted(xx, *coeffs)
    return None


def _select_func(ftype: str):
    """Подобрать функцию и нижнюю границу поиска по строке-типу."""
    if "куб" in ftype:
        return approxmod.cubic_func, 0.0
    if "гипер" in ftype:
        return approxmod.hyperbola_shifted, 1e-6
    if "комб" in ftype:
        return approxmod.combined_shifted, 1e-6
    return None, 0.0


# ============================================================================
# Вкладка 1: Гены и Калибровка
# ============================================================================

class CalibrationWorkspace(QWidget):
    """Основная вкладка — выбор гена и исследования, таблица точек и график."""

    def __init__(self, parent=None, status_cb: StatusFn = _NOOP):
        super().__init__(parent)
        self.status_cb = status_cb
        self.model: QSqlTableModel | None = None
        self._recompute_thread: RecomputeGeneThread | None = None

        self._debounce = QTimer(self, singleShot=True)
        self._debounce.timeout.connect(self._launch_recompute)

        layout = QVBoxLayout(self)
        layout.addLayout(self._build_top_bar())
        layout.addWidget(self._build_splitter())

        self.refresh_after_db_change()

    # === Сборка интерфейса ===

    def _build_top_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Ген:"))
        self.combo_gene = QComboBox()
        self.combo_gene.currentIndexChanged.connect(self._on_gene_changed)
        row.addWidget(self.combo_gene, stretch=1)

        btn_new = QPushButton("Новый ген")
        btn_new.clicked.connect(self._add_new_gene)
        row.addWidget(btn_new)

        row.addSpacing(14)
        row.addWidget(QLabel("Исследование:"))
        self.combo_study = QComboBox()
        self.combo_study.setToolTip(
            "Точки заносятся в рамках выбранного исследования; "
            "можно показать все"
        )
        self.combo_study.currentIndexChanged.connect(self._on_study_changed)
        row.addWidget(self.combo_study, stretch=1)

        row.addSpacing(16)
        self.chk_details = QCheckBox("Показать детали аппроксимации")
        self.chk_details.setToolTip(
            "Показать формулы моделей, метрики и фильтр по типу аппроксимации"
        )
        self.chk_details.toggled.connect(self._toggle_details)
        row.addWidget(self.chk_details)

        self.lbl_display = QLabel("Отображать:")
        row.addWidget(self.lbl_display)
        self.combo_display = QComboBox()
        self.combo_display.addItems(
            ["Все аппроксимации", "Кубическая", "Гипербола", "Комбинированная"]
        )
        self.combo_display.currentIndexChanged.connect(self._redraw)
        row.addWidget(self.combo_display)
        self.lbl_display.hide()
        self.combo_display.hide()
        return row

    def _build_splitter(self) -> QSplitter:
        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)

        toolbar = QHBoxLayout()
        for caption, slot in (
            ("Добавить точку", self._add_point),
            ("Удалить", self._delete_points),
            ("Импорт CSV", self._import_csv),
        ):
            btn = QPushButton(caption)
            toolbar.addWidget(btn)
            btn.clicked.connect(slot)
        ll.addLayout(toolbar)

        self.table_view = CopyableTableView()
        ll.addWidget(self.table_view)
        QShortcut(QKeySequence(Qt.Key_Delete), self.table_view).activated.connect(
            self._delete_points)
        splitter.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)

        self.fig, self.ax = plt.subplots(figsize=(5, 3.5))
        self.canvas = FigureCanvas(self.fig)
        rl.addWidget(self.canvas, stretch=2)

        rrow = QHBoxLayout()
        rrow.addStretch(1)
        btn_export = QPushButton("Экспорт графика")
        btn_export.clicked.connect(self._export_graph)
        rrow.addWidget(btn_export)
        btn_window = QPushButton("Открыть в новом окне")
        btn_window.clicked.connect(self._open_plot_window)
        rrow.addWidget(btn_window)
        rl.addLayout(rrow)

        self.fig_res, self.ax_res = plt.subplots(figsize=(5, 2))
        self.ax_res.axis("off")
        self.canvas_res = FigureCanvas(self.fig_res)
        rl.addWidget(self.canvas_res, stretch=1)
        self.canvas_res.hide()

        splitter.addWidget(right)
        splitter.setSizes([440, 620])
        return splitter

    # === Списки генов и исследований ===

    def refresh_after_db_change(self) -> None:
        self._refresh_studies()
        self.refresh_genes(select_id=self.current_gene_id())

    def _refresh_studies(self) -> None:
        self.combo_study.blockSignals(True)
        self.combo_study.clear()
        self.combo_study.addItem(ALL_STUDIES, userData=None)
        for sid, title in dbmod.fetchall(
                "SELECT StudyID, Title FROM Study ORDER BY StudyID;"):
            self.combo_study.addItem(str(title), userData=sid)
        self.combo_study.blockSignals(False)

    def refresh_genes(self, select_id: int | None = None) -> None:
        self.combo_gene.blockSignals(True)
        self.combo_gene.clear()
        rows = dbmod.fetchall("SELECT GeneID, Name FROM Gene ORDER BY GeneID;")
        idx = 0
        for i, (gid, name) in enumerate(rows):
            self.combo_gene.addItem(f"{name} (ID: {gid})", userData=gid)
            if select_id == gid:
                idx = i
        self.combo_gene.blockSignals(False)
        if rows:
            self.combo_gene.setCurrentIndex(idx)
            self._on_gene_changed()
        else:
            self._clear_visualisation()

    def current_gene_id(self) -> int | None:
        return self.combo_gene.currentData()

    def _current_study_id(self) -> int | None:
        return self.combo_study.currentData()

    def _add_new_gene(self) -> None:
        name, ok = QInputDialog.getText(self, "Новый ген", "Введите название гена:")
        if not (ok and name.strip()):
            return
        with sqlite3.connect(dbmod.DEFAULT_DB) as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO Gene (Name, Description) VALUES (?, '');",
                        (name.strip(),))
            new_id = cur.lastrowid
            conn.commit()
        self.refresh_genes(select_id=new_id)
        self.status_cb(f"Добавлен ген «{name.strip()}»")

    def _on_study_changed(self, *_a) -> None:
        if self.model is not None:
            self._apply_filter()
            self.model.select()

    # === Таблица точек ===

    def _apply_filter(self) -> None:
        gid = self.current_gene_id()
        if gid is None or self.model is None:
            return
        sid = self._current_study_id()
        flt = f"GeneID = {gid}"
        if sid is not None:
            flt += f" AND StudyID = {sid}"
        self.model.setFilter(flt)

    def _on_gene_changed(self) -> None:
        gid = self.current_gene_id()
        if gid is None:
            self._clear_visualisation()
            return
        qdb = _qsql_connection()
        if not qdb:
            return

        self.model = QSqlTableModel(self, qdb)
        self.model.setTable("Calibration")
        self.model.setEditStrategy(QSqlTableModel.OnFieldChange)
        self._apply_filter()
        self.model.select()
        self.model.dataChanged.connect(self._schedule_recompute)
        self.table_view.setModel(self.model)

        # Показываем только содержательные столбцы.
        for col in ("GeneID", "CalibrationID", "StudyID", "ReagentID",
                    "ResearcherID", "MeasurementDate", "Notes"):
            idx = self.model.fieldIndex(col)
            if idx >= 0:
                self.table_view.hideColumn(idx)
        for i in range(self.model.columnCount()):
            field = self.model.record().fieldName(i)
            self.model.setHeaderData(
                i, Qt.Horizontal, resources.COLUMN_NAMES_RU.get(field, field))

        delegate = PercentageDelegate(self.table_view)
        for col in ("CalibrationLevel", "ObservedMethylation"):
            self.table_view.setItemDelegateForColumn(self.model.fieldIndex(col), delegate)
        self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        self._redraw()

    # === Точки: добавление, удаление, импорт ===

    def _add_point(self) -> None:
        gid = self.current_gene_id()
        if gid is None or self.model is None:
            return
        dlg = AddPointDialog(self)
        if not dlg.exec():
            return
        true_val, obs_val = dlg.values()
        sid = self._current_study_id()

        row = self.model.rowCount()
        self.model.insertRow(row)
        self.model.setData(self.model.index(row, self.model.fieldIndex("GeneID")), gid)
        if sid is not None:
            self.model.setData(self.model.index(row, self.model.fieldIndex("StudyID")), sid)
        self.model.setData(self.model.index(row, self.model.fieldIndex("CalibrationLevel")), true_val)
        self.model.setData(self.model.index(row, self.model.fieldIndex("ObservedMethylation")), obs_val)
        self.model.submitAll()
        self._schedule_recompute()

    def _delete_points(self) -> None:
        if self.model is None:
            return
        rows = {idx.row() for idx in self.table_view.selectionModel().selectedIndexes()}
        for r in sorted(rows, reverse=True):
            self.model.removeRow(r)
        self.model.submitAll()
        self.model.select()
        self._schedule_recompute()

    def _import_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Импорт CSV", filter="CSV/TXT (*.csv *.txt);;Все файлы (*)")
        if not path:
            return
        pairs = utils.parse_pairs(path)
        valid = [(t, o) for t, o in pairs if 0 <= t <= 100 and 0 <= o <= 100]
        if not valid:
            QMessageBox.warning(self, "Импорт",
                                "В файле нет валидных пар чисел в диапазоне [0, 100].")
            return

        msg = QMessageBox(self)
        msg.setWindowTitle("Импорт данных")
        msg.setText("Куда импортировать точки?")
        btn_new = msg.addButton("Создать новый ген", QMessageBox.ActionRole)
        btn_cur = msg.addButton("В текущий ген", QMessageBox.ActionRole)
        msg.addButton("Отмена", QMessageBox.RejectRole)
        msg.exec()
        clicked = msg.clickedButton()

        if clicked == btn_new:
            name, ok = QInputDialog.getText(self, "Новый ген", "Название гена:",
                                            text=Path(path).stem)
            if not (ok and name.strip()):
                return
            with sqlite3.connect(dbmod.DEFAULT_DB) as conn:
                cur = conn.cursor()
                cur.execute("INSERT INTO Gene (Name, Description) VALUES (?, ?);",
                            (name.strip(), f"Импорт из {Path(path).name}"))
                gid = cur.lastrowid
                conn.commit()
            self.refresh_genes(select_id=gid)
        elif clicked == btn_cur:
            gid = self.current_gene_id()
            if gid is None:
                QMessageBox.warning(self, "Импорт", "Сначала выберите ген.")
                return
        else:
            return

        sid = self._current_study_id()
        with sqlite3.connect(dbmod.DEFAULT_DB) as conn:
            conn.executemany(
                "INSERT INTO Calibration (GeneID, StudyID, CalibrationLevel, "
                "ObservedMethylation) VALUES (?, ?, ?, ?);",
                [(gid, sid, t, o) for t, o in valid])
            conn.commit()

        skipped = len(pairs) - len(valid)
        tail = f" (пропущено {skipped})" if skipped else ""
        self.status_cb(f"Импортировано {len(valid)} точек{tail}")
        if self.model is not None:
            self.model.select()
        self._schedule_recompute()

    # === Пересчёт в фоне ===

    def _schedule_recompute(self, *_args) -> None:
        self._debounce.start(500)

    def _launch_recompute(self) -> None:
        gid = self.current_gene_id()
        if gid is None:
            return
        if self._recompute_thread and self._recompute_thread.isRunning():
            self._debounce.start(500)
            return
        self.status_cb("Пересчёт усреднений и аппроксимаций…")
        self._recompute_thread = RecomputeGeneThread(dbmod.DEFAULT_DB, gid)
        self._recompute_thread.finished_signal.connect(self._on_recompute_done)
        self._recompute_thread.start()

    def _on_recompute_done(self, ok: bool, msg: str) -> None:
        self.status_cb(msg if ok else f"Внимание: {msg}")
        self._redraw()

    # === Рисование ===

    def _clear_visualisation(self) -> None:
        if self.model:
            self.model.clear()
        self.ax.clear(); self.canvas.draw()
        self.ax_res.clear(); self.ax_res.axis("off"); self.canvas_res.draw()

    def _draw_plot(self, ax, *, full_range: bool = False,
                   detailed: bool | None = None) -> list[dict]:
        if detailed is None:
            detailed = self.chk_details.isChecked()
        ax.clear()
        gid = self.current_gene_id()
        if gid is None:
            return []

        raw = dbmod.fetchall(
            "SELECT CalibrationLevel, ObservedMethylation FROM Calibration WHERE GeneID = ?;",
            (gid,))
        if raw:
            ax.scatter([r[0] for r in raw], [r[1] for r in raw],
                       color="gray", alpha=0.4, s=15, label="Исходные")

        avg = dbmod.fetchall(
            "SELECT CalibrationLevel, AvgObservedMethylation "
            "FROM Avg_Calibration WHERE GeneID = ? ORDER BY CalibrationLevel;",
            (gid,))
        if avg:
            ax.scatter([r[0] for r in avg], [r[1] for r in avg],
                       color="blue", s=30, label="Усреднённые", zorder=5)

        approx_rows = dbmod.fetchall(
            "SELECT FunctionType, Coefficients, StdDeviation, RelativeError "
            "FROM Approximation WHERE GeneID = ?;", (gid,))
        best_type = None
        if approx_rows:
            with_sigma = [r for r in approx_rows if r[2] is not None]
            if with_sigma:
                best_type = min(with_sigma, key=lambda r: r[2])[0]

        display_filter = self.combo_display.currentText()
        if full_range:
            xx = np.concatenate([np.linspace(-50, -0.001, 250),
                                 np.linspace(0.001, 150, 750)])
        else:
            xx = np.linspace(0.001, 100, 500)
        formulas: list[dict] = []

        if not detailed:
            best_row = next((r for r in approx_rows if r[0] == best_type), None)
            if best_row is not None:
                coeffs = approxmod.coeffs_from_json(best_row[1])
                yy = _evaluate(best_row[0], coeffs, xx)
                if yy is not None:
                    ax.plot(xx, yy, label="Калибровочная кривая",
                            linewidth=3, color="#1f77b4", zorder=4)
        else:
            for ftype, coeffs_json, stddev, rel_err in approx_rows:
                display_name = resources.APPROX_DISPLAY.get(ftype, ftype)
                is_best = (ftype == best_type)
                label = display_name + (" ★ (лучшая)" if is_best else "")
                if display_filter != "Все аппроксимации" and display_filter.lower() not in label.lower():
                    continue
                coeffs = approxmod.coeffs_from_json(coeffs_json)
                yy = _evaluate(ftype, coeffs, xx)
                if yy is not None:
                    ax.plot(xx, yy, label=label,
                            linewidth=3 if is_best else 2, zorder=4 if is_best else 3)
                formulas.append({
                    "title": label,
                    "formula": formula_mathtex(ftype, coeffs),
                    "sigma": stddev or 0.0,
                    "rel_err": rel_err or 0.0,
                    "is_best": is_best,
                })

        if full_range:
            ax.set_xlim(-10, 110); ax.set_ylim(-10, 110)
            ax.axhline(0, color="#888", linewidth=0.5)
            ax.axvline(0, color="#888", linewidth=0.5)
        else:
            ax.set_xlim(0, 100); ax.set_ylim(0, 100)
        ax.set_xlabel("Истинное метилирование (%)")
        ax.set_ylabel("Измеренное метилирование (%)")
        ax.grid(True, linestyle="--", alpha=0.7)
        if raw or avg or approx_rows:
            ax.legend(fontsize=8, loc="upper left")
        return formulas

    def _redraw(self) -> None:
        formulas = self._draw_plot(self.ax)
        self.fig.tight_layout()
        self.canvas.draw()
        if self.chk_details.isChecked():
            self._draw_formula_panel(formulas)

    def _toggle_details(self, checked: bool) -> None:
        self.lbl_display.setVisible(checked)
        self.combo_display.setVisible(checked)
        self.canvas_res.setVisible(checked)
        self._redraw()

    def _draw_formula_panel(self, formulas: list[dict]) -> None:
        self.ax_res.clear()
        self.ax_res.axis("off")
        if not formulas:
            self.ax_res.text(0.5, 0.5,
                             "Аппроксимации не рассчитаны.\nДобавьте больше точек.",
                             ha="center", va="center", fontsize=10)
            self.canvas_res.draw()
            return
        formulas.sort(key=lambda f: not f["is_best"])
        y_pos = 0.90
        for f in formulas:
            color = "#006600" if f["is_best"] else "#333"
            self.ax_res.text(0.01, y_pos, f["title"], fontsize=10,
                             fontweight="bold", va="top", color=color)
            self.ax_res.text(0.01, y_pos - 0.12, f"${f['formula']}$",
                             fontsize=11, va="top")
            metrics = f"$\\sigma={f['sigma']:.4f}$\n$\\varepsilon={f['rel_err']:.4f}$"
            self.ax_res.text(0.99, y_pos, metrics, fontsize=9, va="top",
                             ha="right", color="#555")
            y_pos -= 0.25
        self.ax_res.set_ylim(min(0, y_pos), 1.0)
        self.canvas_res.draw()

    def _export_graph(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт графика",
            filter="PNG (*.png);;JPEG (*.jpg);;PDF (*.pdf)")
        if path:
            self.fig.savefig(path, dpi=300, bbox_inches="tight")
            self.status_cb(f"График сохранён: {Path(path).name}")

    def _open_plot_window(self) -> None:
        gid = self.current_gene_id()
        if gid is None:
            QMessageBox.information(self, "График", "Сначала выберите ген.")
            return
        win = PlotWindow(self, title=f"Аппроксимации (ген {gid})")
        win.render(lambda ax: self._draw_plot(ax, full_range=True, detailed=True))
        win.exec()


# ============================================================================
# Вкладка 2: Коррекция
# ============================================================================

class CorrectionWorkspace(QWidget):
    """Коррекция измерений: по введённым y находим x = P⁻¹(y)."""

    PLACEHOLDER = "10.5\n20.1\n35.0"

    def __init__(self, parent=None, status_cb: StatusFn = _NOOP):
        super().__init__(parent)
        self.status_cb = status_cb
        layout = QVBoxLayout(self)
        layout.addLayout(self._build_top_bar())
        layout.addWidget(self._build_splitter())
        self.combo_approx.currentIndexChanged.connect(self._update_chart)
        self.refresh_after_db_change()

    def _build_top_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Ген:"))
        self.combo_gene = QComboBox()
        self.combo_gene.currentIndexChanged.connect(self._on_gene_changed)
        row.addWidget(self.combo_gene, stretch=1)

        row.addSpacing(18)
        row.addWidget(QLabel("Модель аппроксимации:"))
        self.combo_approx = QComboBox()
        self.combo_approx.setToolTip("Выберите модель для коррекции; по умолчанию — лучшая по σ")
        self.combo_approx.setMinimumWidth(260)
        row.addWidget(self.combo_approx, stretch=1)
        return row

    def _build_splitter(self) -> QSplitter:
        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("Измеренные значения (по одному в строке):"))
        self.text_input = QTextEdit()
        self.text_input.setPlaceholderText(self.PLACEHOLDER)
        ll.addWidget(self.text_input)

        toolbar = QHBoxLayout()
        btn_load = QPushButton("Загрузить из файла")
        btn_load.clicked.connect(self._load_file)
        toolbar.addWidget(btn_load)
        btn_clear = QPushButton("Очистить")
        btn_clear.clicked.connect(self.text_input.clear)
        toolbar.addWidget(btn_clear)
        ll.addLayout(toolbar)

        self.btn_calc = QPushButton("Рассчитать истинные значения")
        self.btn_calc.setMinimumHeight(40)
        self.btn_calc.clicked.connect(self._calculate)
        ll.addWidget(self.btn_calc)
        splitter.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.fig, self.ax = plt.subplots(figsize=(4, 3))
        self.canvas = FigureCanvas(self.fig)
        rl.addWidget(self.canvas, stretch=4)

        rl.addWidget(QLabel("Результат коррекции:"))
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Измеренное (%)", "Скорректированное (%)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        rl.addWidget(self.table, stretch=3)

        btn_export = QPushButton("Экспорт в CSV")
        btn_export.clicked.connect(self._export_csv)
        rl.addWidget(btn_export)

        splitter.addWidget(right)
        splitter.setSizes([320, 520])
        return splitter

    def refresh_after_db_change(self) -> None:
        self._refresh_genes()

    def _refresh_genes(self) -> None:
        self.combo_gene.blockSignals(True)
        self.combo_gene.clear()
        rows = dbmod.fetchall("SELECT GeneID, Name FROM Gene ORDER BY GeneID;")
        for gid, name in rows:
            self.combo_gene.addItem(f"{name} (ID: {gid})", userData=gid)
        self.combo_gene.blockSignals(False)
        if rows:
            self._on_gene_changed()

    def _on_gene_changed(self) -> None:
        self.combo_approx.blockSignals(True)
        self.combo_approx.clear()
        gid = self.combo_gene.currentData()
        if gid is None:
            self.combo_approx.blockSignals(False)
            return
        rows = dbmod.fetchall(
            "SELECT FunctionType, Coefficients, StdDeviation "
            "FROM Approximation WHERE GeneID = ? ORDER BY ApproximationID;", (gid,))
        best_idx, best_sigma = 0, float("inf")
        for i, (ftype, coeffs, sigma) in enumerate(rows):
            label = resources.APPROX_DISPLAY.get(ftype, ftype)
            if sigma is not None and sigma < best_sigma:
                best_sigma, best_idx = sigma, i
            self.combo_approx.addItem(label, userData=(ftype, coeffs))
        if rows:
            current = self.combo_approx.itemText(best_idx)
            self.combo_approx.setItemText(best_idx, current + " ★ (лучшая)")
            self.combo_approx.setCurrentIndex(best_idx)
        self.combo_approx.blockSignals(False)
        self._update_chart()

    def _load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Открыть файл", filter="Text/CSV (*.txt *.csv);;Все файлы (*)")
        if not path:
            return
        nums = utils.parse_file(path)
        self.text_input.setPlainText("\n".join(str(x) for x in nums))

    def _calculate(self) -> None:
        gid = self.combo_gene.currentData()
        data = self.combo_approx.currentData()
        if gid is None or data is None:
            QMessageBox.warning(self, "Коррекция", "Выберите ген и модель.")
            return
        ftype, coeffs_json = data
        coeffs = approxmod.coeffs_from_json(coeffs_json)
        func, lower = _select_func(ftype)
        if func is None:
            QMessageBox.warning(self, "Коррекция", "Неизвестный тип аппроксимации.")
            return

        nums = utils.parse_numbers_from_text(self.text_input.toPlainText())
        valid = [n for n in nums if 0 <= n <= 100]
        if not valid:
            QMessageBox.warning(self, "Коррекция", "Нет валидных чисел в диапазоне [0, 100].")
            return
        if len(valid) < len(nums):
            self.status_cb(f"Пропущено {len(nums) - len(valid)} значений вне [0, 100]")

        max_cal_rows = dbmod.fetchall(
            "SELECT MAX(CalibrationLevel) FROM Avg_Calibration WHERE GeneID = ?;", (gid,))
        max_cal = float(max_cal_rows[0][0]) if max_cal_rows and max_cal_rows[0][0] else 100.0
        upper = max(100.0, max_cal * 1.2)

        self.table.setRowCount(len(valid))
        xs, ys = [], []
        for i, y in enumerate(valid):
            x = approxmod.correct_value(func, coeffs, y, lower=lower, upper=upper)
            self.table.setItem(i, 0, QTableWidgetItem(f"{y:.4f}"))
            self.table.setItem(i, 1, QTableWidgetItem(f"{x:.4f}"))
            xs.append(x); ys.append(y)

        self._update_chart(points=(xs, ys))
        self.status_cb(f"Скорректировано {len(valid)} значений")

    def _update_chart(self, *args, points=None) -> None:
        if points is not None and not isinstance(points, tuple):
            points = None
        self.ax.clear()
        self.ax.set_xlim(0, 100); self.ax.set_ylim(0, 100)
        self.ax.set_xlabel("Истинное метилирование (%)")
        self.ax.set_ylabel("Измеренное метилирование (%)")
        self.ax.set_title("Кривая коррекции")
        self.ax.grid(True, linestyle="--", alpha=0.6)

        data = self.combo_approx.currentData()
        if data is not None:
            ftype, coeffs_json = data
            coeffs = approxmod.coeffs_from_json(coeffs_json)
            xx = np.linspace(0.001, 100, 500)
            yy = _evaluate(ftype, coeffs, xx)
            if yy is not None:
                label = resources.APPROX_DISPLAY.get(ftype, ftype)
                self.ax.plot(xx, yy, "b-", alpha=0.7, label=label)
        if points and points[0]:
            self.ax.scatter(points[0], points[1], color="red", s=30,
                            label="Скорректированные", zorder=5)
        if self.ax.has_data():
            self.ax.legend(fontsize=8)
        self.fig.tight_layout()
        self.canvas.draw()

    def _export_csv(self) -> None:
        if self.table.rowCount() == 0:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт", filter="CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Observed", "Corrected"])
            for r in range(self.table.rowCount()):
                writer.writerow([self.table.item(r, 0).text(),
                                 self.table.item(r, 1).text()])
        self.status_cb(f"Экспорт сохранён: {Path(path).name}")


# ============================================================================
# Вкладка 3: Справочные данные
# ============================================================================

class ReferenceEditorWorkspace(QWidget):
    """
    Редактор справочных и сопутствующих данных: исследователи, публикации,
    реактивы, исследования, праймеры и этапы амплификации. Идентификаторы и
    авторасчётные поля скрыты, внешние ключи выбираются из выпадающих списков.
    """

    def __init__(self, parent=None, status_cb: StatusFn = _NOOP):
        super().__init__(parent)
        self.status_cb = status_cb
        self.entity: RefEntity = REFERENCE_ENTITIES[0]
        self._row_ids: list[int] = []

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Раздел:"))
        self.combo = QComboBox()
        for ent in REFERENCE_ENTITIES:
            self.combo.addItem(ent.label, userData=ent.table)
        self.combo.currentIndexChanged.connect(self._on_entity_changed)
        row.addWidget(self.combo, stretch=1)
        btn_add = QPushButton("Добавить")
        btn_add.clicked.connect(self._add_record)
        row.addWidget(btn_add)
        btn_edit = QPushButton("Изменить")
        btn_edit.clicked.connect(self._edit_record)
        row.addWidget(btn_edit)
        btn_del = QPushButton("Удалить")
        btn_del.clicked.connect(self._delete_record)
        row.addWidget(btn_del)
        layout.addLayout(row)

        self.hint = QLabel()
        self.hint.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(self.hint)

        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.doubleClicked.connect(self._edit_record)
        layout.addWidget(self.table)

        self.refresh_after_db_change()

    def refresh_after_db_change(self) -> None:
        self._reload()

    def _on_entity_changed(self) -> None:
        table = self.combo.currentData()
        for ent in REFERENCE_ENTITIES:
            if ent.table == table:
                self.entity = ent
                break
        self._reload()

    def _reload(self) -> None:
        ent = self.entity
        if ent.table in ("Primers", "AmplificationStep"):
            self.hint.setText("Данные привязаны к конкретному гену (выбирается при добавлении).")
        else:
            self.hint.setText("")
        headers = [f.label for f in ent.fields]
        self.table.clear()
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)

        fk_maps: dict[str, dict] = {}
        for f in ent.fields:
            if f.type == F_FK:
                fk_maps[f.db] = dict(_fk_options(f))

        cols = [ent.pk] + [f.db for f in ent.fields]
        try:
            raw = dbmod.fetchall(f"SELECT {', '.join(cols)} FROM {ent.table} ORDER BY {ent.pk};")
        except Exception:
            raw = []

        self._row_ids = []
        self.table.setRowCount(len(raw))
        for r, record in enumerate(raw):
            self._row_ids.append(record[0])
            for c, f in enumerate(ent.fields):
                value = record[c + 1]
                if f.type == F_FK:
                    text = fk_maps[f.db].get(value, "" if value is None else f"#{value}")
                elif value is None:
                    text = ""
                else:
                    text = str(value)
                self.table.setItem(r, c, QTableWidgetItem(text))
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)

    def _selected_row(self) -> int | None:
        rows = {idx.row() for idx in self.table.selectionModel().selectedRows()}
        if not rows:
            rows = {idx.row() for idx in self.table.selectedIndexes()}
        return min(rows) if rows else None

    def _add_record(self) -> None:
        ent = self.entity
        for f in ent.fields:
            if f.type == F_FK and f.required and not _fk_options(f):
                QMessageBox.information(
                    self, "Нет данных",
                    f"Сначала добавьте хотя бы одну запись в раздел "
                    f"«{resources.TABLE_LABELS.get(f.fk_table, f.fk_table)}», "
                    f"чтобы выбрать значение поля «{f.label}».")
                return
        dlg = RecordFormDialog(ent, parent=self)
        if not dlg.exec():
            return
        self._insert(ent, dlg.values())

    def _edit_record(self) -> None:
        r = self._selected_row()
        if r is None:
            self.status_cb("Выберите строку для изменения")
            return
        ent = self.entity
        row_id = self._row_ids[r]
        cols = [f.db for f in ent.fields]
        rec = dbmod.fetchall(
            f"SELECT {', '.join(cols)} FROM {ent.table} WHERE {ent.pk} = ?;", (row_id,))
        if not rec:
            return
        values = dict(zip(cols, rec[0]))
        dlg = RecordFormDialog(ent, values=values, parent=self)
        if not dlg.exec():
            return
        self._update(ent, row_id, dlg.values())

    def _delete_record(self) -> None:
        r = self._selected_row()
        if r is None:
            self.status_cb("Выберите строку для удаления")
            return
        ent = self.entity
        row_id = self._row_ids[r]
        if QMessageBox.question(self, "Удаление",
                                f"Удалить выбранную запись из раздела «{ent.label}»?") != QMessageBox.Yes:
            return
        try:
            dbmod.execute_sql(f"DELETE FROM {ent.table} WHERE {ent.pk} = ?;", (row_id,))
            self.status_cb("Запись удалена")
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось удалить: {e}")
        self._reload()

    def _insert(self, ent: RefEntity, values: dict) -> None:
        cols = list(values.keys())
        placeholders = ", ".join("?" for _ in cols)
        sql = f"INSERT INTO {ent.table} ({', '.join(cols)}) VALUES ({placeholders});"
        try:
            dbmod.execute_sql(sql, tuple(values[c] for c in cols))
            self.status_cb("Запись добавлена")
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось добавить: {e}")
        self._reload()
        self.table.scrollToBottom()

    def _update(self, ent: RefEntity, row_id: int, values: dict) -> None:
        cols = list(values.keys())
        set_clause = ", ".join(f"{c} = ?" for c in cols)
        sql = f"UPDATE {ent.table} SET {set_clause} WHERE {ent.pk} = ?;"
        try:
            dbmod.execute_sql(sql, tuple(values[c] for c in cols) + (row_id,))
            self.status_cb("Запись изменена")
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось сохранить: {e}")
        self._reload()
