"""
Точка входа: стартовый диалог + главное окно.

Поток управления:
  StartDialog → пользователь выбирает или создаёт файл БД
              → MainWindow открывается на этом файле.

Все три кнопки в верхней панели (Открыть / Создать / Экспорт) работают
с тем же объектом QSqlDatabase под именем «methyl_conn».
"""

import logging
import sys
from pathlib import Path

from PySide6.QtCore import Qt
import tempfile

from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPushButton, QStatusBar, QTabWidget, QVBoxLayout, QWidget,
)
from PySide6.QtSql import QSqlDatabase

import db as dbmod
from resources import APP_TITLE
from tabs import (
    CalibrationWorkspace, CorrectionWorkspace, ReferenceEditorWorkspace,
)

# Глобальный стиль: чуть крупнее кнопки и шрифт — удобнее и читаемее.
APP_STYLE = """
QPushButton { padding: 6px 14px; font-size: 11pt; }
QComboBox, QLineEdit, QTextEdit { font-size: 11pt; padding: 2px 4px; }
QTabBar::tab { padding: 8px 18px; font-size: 11pt; }
QLabel { font-size: 11pt; }
QTableView, QTableWidget { font-size: 11pt; }
"""


logging.basicConfig(
    filename="methylation.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

CONNECTION_NAME = "methyl_conn"


class StartDialog(QDialog):
    """Первый экран приложения: открыть или создать файл БД."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(APP_TITLE)
        self.resize(450, 250)
        self.db_path: str | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(40, 40, 40, 40)

        title = QLabel(APP_TITLE)
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Выберите действие для начала работы")
        subtitle.setStyleSheet("font-size: 13px;")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)
        layout.addSpacing(20)

        btn_open = QPushButton("Открыть базу данных")
        btn_open.setMinimumHeight(40)
        btn_open.setCursor(Qt.PointingHandCursor)
        btn_open.clicked.connect(self._open)
        layout.addWidget(btn_open)

        btn_create = QPushButton("Создать новую базу")
        btn_create.setMinimumHeight(40)
        btn_create.setCursor(Qt.PointingHandCursor)
        btn_create.clicked.connect(self._create)
        layout.addWidget(btn_create)

        btn_demo = QPushButton("Запустить демонстрацию")
        btn_demo.setMinimumHeight(40)
        btn_demo.setCursor(Qt.PointingHandCursor)
        btn_demo.setToolTip("Создать готовую базу с примерами: гены, "
                            "исследования и калибровочные точки")
        btn_demo.clicked.connect(self._demo)
        layout.addWidget(btn_demo)

        hint = QLabel("Демонстрация создаёт пример с тремя генами, "
                      "исследованиями и точками — можно сразу всё посмотреть.")
        hint.setStyleSheet("color: gray; font-size: 11px;")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint)

        layout.addStretch()

    def _open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Открыть БД",
            filter="SQLite (*.sqlite3 *.db);;Все файлы (*)",
        )
        if path:
            self.db_path = path
            self.accept()

    def _create(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Создать БД", filter="SQLite (*.sqlite3 *.db)",
        )
        if not path:
            return
        try:
            dbmod.init_sqlite(path)
            self.db_path = path
            self.accept()
        except Exception as e:
            logger.exception("Не удалось создать БД")
            QMessageBox.critical(self, "Ошибка", f"Не удалось создать БД: {e}")

    def _demo(self) -> None:
        """Создать готовую демонстрационную базу и открыть её."""
        import os
        path = os.path.join(tempfile.gettempdir(), "methyl_demo.sqlite3")
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
        try:
            dbmod.seed_demo(path)
            self.db_path = path
            self.accept()
        except Exception as e:
            logger.exception("Не удалось создать демонстрационную базу")
            QMessageBox.critical(self, "Ошибка", f"Не удалось создать демо: {e}")


class MainWindow(QMainWindow):
    """Главное окно: верхняя панель с операциями над БД + единый рабочий экран."""

    def __init__(self, db_path: str):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1400, 880)
        self.db_path = db_path

        self._open_database(db_path)
        self._build_ui()
        self._refresh_all()

    # === Управление базой ===

    def _open_database(self, db_path: str) -> None:
        """Подготовить схему и открыть соединение."""
        dbmod.init_sqlite(db_path)  # idempotent: создаст файл/таблицы при необходимости
        self.qdb = dbmod.open_qt_sql(db_path, connection_name=CONNECTION_NAME)
        dbmod.DEFAULT_DB = db_path
        self.db_path = db_path
        logger.info("Открыта БД: %s", db_path)

    def _menu_open_db(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Открыть БД",
            filter="SQLite (*.sqlite3 *.db);;Все файлы (*)",
        )
        if not path:
            return
        try:
            self._open_database(path)
            self._refresh_all()
            self._status(f"Открыта база: {Path(path).name}")
        except Exception as e:
            logger.exception("Не удалось открыть БД")
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть базу: {e}")

    def _menu_create_db(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Создать БД", filter="SQLite (*.sqlite3 *.db)",
        )
        if not path:
            return
        try:
            self._open_database(path)
            self._refresh_all()
            self._status(f"Создана база: {Path(path).name}")
        except Exception as e:
            logger.exception("Не удалось создать БД")
            QMessageBox.critical(self, "Ошибка", f"Не удалось создать базу: {e}")

    def _menu_export_db(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт БД", filter="SQLite (*.sqlite3 *.db)",
        )
        if not path:
            return
        try:
            dbmod.export_db(self.db_path, path)
            self._status(f"База экспортирована: {Path(path).name}")
        except Exception as e:
            logger.exception("Экспорт БД не удался")
            QMessageBox.critical(self, "Ошибка", f"Экспорт не удался: {e}")

    # === Сборка интерфейса ===

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        layout.addLayout(self._build_top_bar())

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, stretch=1)

        self.calib_tab = CalibrationWorkspace(status_cb=self._status)
        self.corr_tab = CorrectionWorkspace(status_cb=self._status)
        self.ref_tab = ReferenceEditorWorkspace(status_cb=self._status)

        self.tabs.addTab(self.calib_tab, "Гены и калибровка")
        self.tabs.addTab(self.corr_tab, "Коррекция")
        self.tabs.addTab(self.ref_tab, "Справочные данные")
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self._status(f"База: {Path(self.db_path).name}")

    def _build_top_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Операции с базой:"))

        btn_open = QPushButton("Открыть БД")
        btn_open.setToolTip("Открыть существующий файл SQLite")
        btn_open.clicked.connect(self._menu_open_db)
        row.addWidget(btn_open)

        btn_create = QPushButton("Создать БД")
        btn_create.setToolTip("Создать новый файл с готовой схемой")
        btn_create.clicked.connect(self._menu_create_db)
        row.addWidget(btn_create)

        btn_export = QPushButton("Экспорт БД")
        btn_export.setToolTip("Сохранить копию текущей базы")
        btn_export.clicked.connect(self._menu_export_db)
        row.addWidget(btn_export)

        row.addStretch()
        return row

    # === Обновление вкладок ===

    def _on_tab_changed(self, index: int) -> None:
        widgets = [self.calib_tab, self.corr_tab, self.ref_tab]
        widget = widgets[index] if 0 <= index < len(widgets) else None
        if widget and hasattr(widget, "refresh_after_db_change"):
            widget.refresh_after_db_change()

    def _refresh_all(self) -> None:
        for w in (self.calib_tab, self.corr_tab, self.ref_tab):
            w.refresh_after_db_change()

    def _status(self, text: str) -> None:
        """Вывести сообщение в статус-бар на 5 секунд."""
        if hasattr(self, "status_bar"):
            self.status_bar.showMessage(text, 5000)


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLE)

    # Файл БД можно передать первым аргументом — удобно для отладки.
    if len(sys.argv) > 1 and Path(sys.argv[1]).exists():
        db_path = sys.argv[1]
    else:
        dlg = StartDialog()
        if dlg.exec() != QDialog.Accepted or not dlg.db_path:
            return
        db_path = dlg.db_path

    win = MainWindow(db_path)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
