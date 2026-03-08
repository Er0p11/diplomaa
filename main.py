import sys
import logging
import shutil
from pathlib import Path
import sqlite3

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QMessageBox, QTabWidget, QDialog
)
from PySide6.QtCore import Qt
from PySide6.QtSql import QSqlDatabase

import db as dbmod
from tabs import CalibrationWorkspace, CorrectionWorkspace, DatabaseEditorWorkspace, HelpWorkspace

# logging
logging.basicConfig(
    filename="methylation.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)

def ensure_schema(db_path: str):
    """
    Проверяет наличие таблицы Gene. Если нет — вызывает dbmod.init_sqlite (если доступен).
    """
    try:
        if not Path(db_path).exists():
            if hasattr(dbmod, 'init_sqlite'):
                dbmod.init_sqlite(db_path)
            else:
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
                open(db_path, 'a').close()
            return
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Gene';")
        row = cur.fetchone()
        conn.close()
        if not row:
            if hasattr(dbmod, 'init_sqlite'):
                dbmod.init_sqlite(db_path)
            else:
                logger.warning("Schema missing and init_sqlite not available for %s", db_path)
    except Exception as e:
        logger.exception("ensure_schema failed for %s", db_path)
        raise

class StartDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Менеджер метилирования")
        self.resize(450, 250)
        self.db_path = None

        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(40, 40, 40, 40)

        # Title
        title = QLabel("Менеджер метилирования")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        subtitle = QLabel("Выберите действие для начала работы")
        subtitle.setStyleSheet("font-size: 13px;")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)

        layout.addSpacing(20)

        # Buttons
        self.btn_open = QPushButton("Открыть базу данных")
        self.btn_open.setMinimumHeight(40)
        self.btn_open.setCursor(Qt.PointingHandCursor)
        
        self.btn_create = QPushButton("Создать новую базу")
        self.btn_create.setMinimumHeight(40)
        self.btn_create.setCursor(Qt.PointingHandCursor)
        
        layout.addWidget(self.btn_open)
        layout.addWidget(self.btn_create)
        
        layout.addStretch()

        self.btn_open.clicked.connect(self.open_db)
        self.btn_create.clicked.connect(self.create_db)

    def open_db(self):
        path, _ = QFileDialog.getOpenFileName(self, "Открыть БД", filter="SQLite (*.sqlite3 *.db);;Все файлы (*)")
        if path:
            self.db_path = path
            self.accept()

    def create_db(self):
        path, _ = QFileDialog.getSaveFileName(self, "Создать БД", filter="SQLite (*.sqlite3 *.db)")
        if not path:
            return
        try:
            if hasattr(dbmod, 'init_sqlite'):
                dbmod.init_sqlite(path)
            else:
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                open(path, 'a').close()
            self.db_path = path
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось создать БД: {e}")

class MainWindow(QMainWindow):
    def __init__(self, db_path: str):
        super().__init__()
        self.setWindowTitle("Менеджер метилирования")
        self.resize(1280, 820)

        self.conn_name = "methyl_conn"
        self.db_path = db_path

        # ensure schema before opening
        try:
            ensure_schema(self.db_path)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось подготовить базу данных: {e}")
            logger.exception("Failed to ensure schema for %s", self.db_path)
            sys.exit(1)

        # open QSqlDatabase (use helper if present)
        try:
            if hasattr(dbmod, 'open_qt_sql'):
                self.qdb = dbmod.open_qt_sql(self.db_path, connection_name=self.conn_name)
            else:
                if QSqlDatabase.contains(self.conn_name):
                    try:
                        old = QSqlDatabase.database(self.conn_name)
                        if old.isOpen():
                            old.close()
                    except Exception:
                        pass
                    QSqlDatabase.removeDatabase(self.conn_name)
                db = QSqlDatabase.addDatabase("QSQLITE", self.conn_name)
                db.setDatabaseName(str(self.db_path))
                if not db.open():
                    raise RuntimeError("Не удалось открыть SQLite через QSqlDatabase.")
                self.qdb = db
            # set DEFAULT_DB for dbmod if available
            if hasattr(dbmod, 'DEFAULT_DB'):
                dbmod.DEFAULT_DB = self.db_path
            logger.info("Opened DB via QSql: %s", self.db_path)
        except Exception as e:
            logger.exception("Failed to open DB via QSql")
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть базу данных: {e}")
            sys.exit(1)

        # build UI and top buttons
        self._build_ui()
        # refresh after everything created and dbmod.DEFAULT_DB set
        self.refresh_all()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Top row: 3 big buttons (Open / Create / Export)
        top_row = QHBoxLayout()
        lbl = QLabel("Операции с базой:")
        top_row.addWidget(lbl)
        btn_open = QPushButton("Открыть БД")
        btn_open.setToolTip("Открыть существующий файл SQLite")
        btn_open.clicked.connect(self.menu_open_db)
        top_row.addWidget(btn_open)
        btn_create = QPushButton("Создать БД")
        btn_create.setToolTip("Создать новую базу (инициализирует схему)")
        btn_create.clicked.connect(self.menu_create_db)
        top_row.addWidget(btn_create)
        btn_export = QPushButton("Экспорт БД")
        btn_export.setToolTip("Экспортировать текущую базу в файл")
        btn_export.clicked.connect(self.menu_export_db)
        top_row.addWidget(btn_export)
        top_row.addStretch()
        layout.addLayout(top_row)

        # Tabs
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # create tabs
        self.calib_tab = CalibrationWorkspace()
        self.corr_tab = CorrectionWorkspace()
        self.ref_tab = DatabaseEditorWorkspace()
        self.help_tab = HelpWorkspace()

        # Connect signals so that when genes change, other tabs update
        # We don't have a specific signal, but we can just refresh when tabs change
        self.tabs.currentChanged.connect(self.on_tab_changed)

        self.tabs.addTab(self.calib_tab, "Гены и Калибровка")
        self.tabs.addTab(self.corr_tab, "Коррекция")
        self.tabs.addTab(self.ref_tab, "Редактор БД")
        self.tabs.addTab(self.help_tab, "Справка")

    def on_tab_changed(self, index):
        self.refresh_all()

    def menu_open_db(self):
        path, _ = QFileDialog.getOpenFileName(self, "Открыть БД", filter="SQLite (*.sqlite3 *.db);;Все файлы (*)")
        if not path:
            return
        try:
            ensure_schema(path)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось подготовить выбранную базу: {e}")
            logger.exception("ensure_schema failed for %s", path)
            return
        try:
            if QSqlDatabase.contains(self.conn_name):
                old = QSqlDatabase.database(self.conn_name)
                try:
                    if old.isOpen():
                        old.close()
                except Exception:
                    pass
                QSqlDatabase.removeDatabase(self.conn_name)
        except Exception:
            pass
        try:
            if hasattr(dbmod, 'open_qt_sql'):
                self.qdb = dbmod.open_qt_sql(path, connection_name=self.conn_name)
            else:
                db = QSqlDatabase.addDatabase("QSQLITE", self.conn_name)
                db.setDatabaseName(str(path))
                if not db.open():
                    raise RuntimeError("Не удалось открыть QSQLITE")
                self.qdb = db
            self.db_path = path
            if hasattr(dbmod, 'DEFAULT_DB'):
                dbmod.DEFAULT_DB = path
            self.refresh_all()
            QMessageBox.information(self, "БД открыта", f"Открыта база: {path}")
            logger.info("Switched DB to: %s", path)
        except Exception as e:
            logger.exception("menu_open_db failed")
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть базу: {e}")

    def menu_create_db(self):
        path, _ = QFileDialog.getSaveFileName(self, "Создать БД", filter="SQLite (*.sqlite3 *.db)")
        if not path:
            return
        try:
            if hasattr(dbmod, 'init_sqlite'):
                dbmod.init_sqlite(path)
            else:
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                open(path, 'a').close()
            # reopen
            try:
                if QSqlDatabase.contains(self.conn_name):
                    old = QSqlDatabase.database(self.conn_name)
                    try:
                        if old.isOpen():
                            old.close()
                    except Exception:
                        pass
                    QSqlDatabase.removeDatabase(self.conn_name)
            except Exception:
                pass
            if hasattr(dbmod, 'open_qt_sql'):
                self.qdb = dbmod.open_qt_sql(path, connection_name=self.conn_name)
            else:
                db = QSqlDatabase.addDatabase("QSQLITE", self.conn_name)
                db.setDatabaseName(str(path))
                if not db.open():
                    raise RuntimeError("Не удалось открыть QSQLITE")
                self.qdb = db
            self.db_path = path
            if hasattr(dbmod, 'DEFAULT_DB'):
                dbmod.DEFAULT_DB = path
            self.refresh_all()
            QMessageBox.information(self, "Создано", f"База данных создана: {path}")
            logger.info("Created DB: %s", path)
        except Exception as e:
            logger.exception("menu_create_db failed")
            QMessageBox.critical(self, "Ошибка", f"Не удалось создать базу: {e}")

    def menu_export_db(self):
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт БД", filter="SQLite (*.sqlite3 *.db)")
        if not path:
            return
        try:
            try:
                if hasattr(dbmod, 'export_db'):
                    try:
                        dbmod.export_db(dbmod.DEFAULT_DB, path)
                    except TypeError:
                        try:
                            dbmod.export_db(db_path=dbmod.DEFAULT_DB, dest_path=path)
                        except TypeError:
                            shutil.copy(dbmod.DEFAULT_DB, path)
                else:
                    shutil.copy(dbmod.DEFAULT_DB, path)
            except Exception:
                shutil.copy(dbmod.DEFAULT_DB, path)
            QMessageBox.information(self, "Экспорт", "База данных экспортирована.")
            logger.info("Exported DB to: %s", path)
        except Exception as e:
            logger.exception("menu_export_db failed")
            QMessageBox.critical(self, "Ошибка", f"Экспорт не удался: {e}")

    def refresh_all(self):
        try:
            self.calib_tab.refresh_genes(select_id=self.calib_tab.current_gene_id())
        except Exception:
            pass
        try:
            self.corr_tab.refresh_genes()
        except Exception:
            pass
        try:
            self.ref_tab.refresh_tables()
        except Exception:
            pass

def main():
    app = QApplication(sys.argv)
    dlg = StartDialog()
    if dlg.exec() != QDialog.Accepted or not dlg.db_path:
        sys.exit(0)
    win = MainWindow(dlg.db_path)
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
