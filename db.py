"""
Работа с SQLite: создание схемы, подключения, экспорт файла БД.

Используется два API:
  * sqlite3 — стандартный модуль Python, нужен для разовых SQL-запросов
    (выборки в графиках, пересчёт усреднений и т.п.).
  * QSqlDatabase из PySide6 — нужен моделям QSqlTableModel,
    которые отображают таблицы в QTableView.
"""

import shutil
import sqlite3
from pathlib import Path

from PySide6.QtSql import QSqlDatabase


SCHEMA_SQL = r"""
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS Gene (
    GeneID INTEGER PRIMARY KEY AUTOINCREMENT,
    Name TEXT NOT NULL,
    Description TEXT
);

CREATE TABLE IF NOT EXISTS Researchers (
    ResearcherID INTEGER PRIMARY KEY AUTOINCREMENT,
    FullName TEXT NOT NULL,
    Workplace TEXT,
    Email TEXT
);

CREATE TABLE IF NOT EXISTS Publications (
    PublicationID INTEGER PRIMARY KEY AUTOINCREMENT,
    Title TEXT NOT NULL,
    Journal TEXT,
    Volume INTEGER,
    Year INTEGER,
    Pages INTEGER,
    ResearcherID INTEGER NOT NULL,
    FOREIGN KEY (ResearcherID) REFERENCES Researchers(ResearcherID) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS Reagents (
    ReagentID INTEGER PRIMARY KEY AUTOINCREMENT,
    Name TEXT NOT NULL,
    Manufacturer TEXT,
    Country TEXT,
    CatalogNumber TEXT
);

CREATE TABLE IF NOT EXISTS Study (
    StudyID INTEGER PRIMARY KEY AUTOINCREMENT,
    Title TEXT NOT NULL,
    ResearcherID INTEGER NOT NULL,
    PublicationID INTEGER,
    Date DATE,
    FOREIGN KEY (ResearcherID) REFERENCES Researchers(ResearcherID) ON DELETE CASCADE,
    FOREIGN KEY (PublicationID) REFERENCES Publications(PublicationID) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS Calibration (
    CalibrationID INTEGER PRIMARY KEY AUTOINCREMENT,
    GeneID INTEGER NOT NULL,
    StudyID INTEGER,
    CalibrationLevel REAL NOT NULL,
    ObservedMethylation REAL NOT NULL,
    ReagentID INTEGER,
    ResearcherID INTEGER,
    MeasurementDate DATE,
    Notes TEXT,
    FOREIGN KEY (GeneID) REFERENCES Gene(GeneID) ON DELETE CASCADE,
    FOREIGN KEY (StudyID) REFERENCES Study(StudyID) ON DELETE SET NULL,
    FOREIGN KEY (ReagentID) REFERENCES Reagents(ReagentID) ON DELETE SET NULL,
    FOREIGN KEY (ResearcherID) REFERENCES Researchers(ResearcherID) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS Avg_Calibration (
    AvgID INTEGER PRIMARY KEY AUTOINCREMENT,
    GeneID INTEGER NOT NULL,
    CalibrationLevel REAL NOT NULL,
    AvgObservedMethylation REAL NOT NULL,
    CountMeasurements INTEGER NOT NULL,
    FOREIGN KEY (GeneID) REFERENCES Gene(GeneID) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS Primers (
    PrimerID INTEGER PRIMARY KEY AUTOINCREMENT,
    GeneID INTEGER NOT NULL,
    Sequence TEXT NOT NULL,
    GeneCopySize INTEGER,
    CpGPositions INTEGER,
    FOREIGN KEY (GeneID) REFERENCES Gene(GeneID) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS AmplificationStep (
    AmplificationID INTEGER PRIMARY KEY AUTOINCREMENT,
    GeneID INTEGER NOT NULL,
    StepNumber INTEGER NOT NULL,
    Temperature REAL,
    DurationSeconds INTEGER,
    FOREIGN KEY (GeneID) REFERENCES Gene(GeneID) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS Approximation (
    ApproximationID INTEGER PRIMARY KEY AUTOINCREMENT,
    GeneID INTEGER NOT NULL,
    FunctionType TEXT NOT NULL,
    Coefficients TEXT NOT NULL,
    StdDeviation REAL,
    RelativeError REAL,
    AdditionalMetrics TEXT,
    CreatedAt DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (GeneID) REFERENCES Gene(GeneID) ON DELETE CASCADE,
    UNIQUE(GeneID, FunctionType)
);

CREATE INDEX IF NOT EXISTS idx_calibration_gene ON Calibration(GeneID);
CREATE INDEX IF NOT EXISTS idx_avg_cal_gene     ON Avg_Calibration(GeneID);
CREATE INDEX IF NOT EXISTS idx_approx_gene      ON Approximation(GeneID);
"""

# Текущий путь к открытому файлу БД. Меняется при открытии другой базы.
DEFAULT_DB = str(Path.cwd() / "methyl_data_full.sqlite3")


def init_sqlite(db_path: str) -> str:
    """Создать файл БД (если нет) и накатить схему. Идемпотентно."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()
    return db_path


def open_qt_sql(db_path: str, connection_name: str = "methyl_conn") -> QSqlDatabase:
    """Открыть БД через QSqlDatabase, пересоздав соединение если оно уже было."""
    if QSqlDatabase.contains(connection_name):
        old = QSqlDatabase.database(connection_name)
        if old.isOpen():
            old.close()
        QSqlDatabase.removeDatabase(connection_name)

    db = QSqlDatabase.addDatabase("QSQLITE", connection_name)
    db.setDatabaseName(str(db_path))
    if not db.open():
        raise RuntimeError(f"Не удалось открыть SQLite через QSqlDatabase: {db_path}")
    return db


def fetchall(sql: str, params: tuple = (), db_path: str | None = None) -> list[tuple]:
    """Выполнить SELECT и вернуть все строки."""
    conn = sqlite3.connect(db_path or DEFAULT_DB)
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        conn.close()


def execute_sql(sql: str, params: tuple = (), db_path: str | None = None) -> None:
    """Выполнить произвольный SQL с коммитом."""
    conn = sqlite3.connect(db_path or DEFAULT_DB)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def export_db(src_path: str, dest_path: str) -> str:
    """Скопировать файл БД в указанное место (используется в «Экспорт БД»)."""
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(str(src_path), str(dest_path))
    return str(dest_path)


# ============================================================================
# Демонстрационная база данных (создаётся из приложения по кнопке «Демо»)
# ============================================================================

_DEMO_RESEARCHERS = [
    ("Иванов И. И.", "Институт генетики", "ivanov@example.com"),
    ("Петрова А. С.", "Лаборатория биоинформатики", "petrova@example.com"),
]
_DEMO_REAGENTS = [
    ("EpiTect Bisulfite Kit", "Qiagen", "Германия", "59104"),
    ("EZ DNA Methylation Kit", "Zymo Research", "США", "D5001"),
]
_DEMO_GENES = [
    ("MGMT", "O-6-метилгуанин-ДНК-метилтрансфераза"),
    ("MLH1", "MutL homolog 1"),
    ("CDKN2A", "Cyclin-dependent kinase inhibitor 2A"),
]
# «Идеальная» форма зависимости измеренного значения от истинного для каждого гена.
_DEMO_PROFILES = {
    "MGMT": lambda x: 100 * (3 * x ** 2 - 2 * x ** 3),   # S-образная
    "MLH1": lambda x: 100 * (x ** 0.5),                   # выпуклая
    "CDKN2A": lambda x: 100 * x,                          # линейная
}
_DEMO_NOISE = {"MGMT": 3, "MLH1": 4, "CDKN2A": 5}


def seed_demo(db_path: str) -> str:
    """
    Создать и наполнить демонстрационную базу: исследователи, реактивы, гены,
    исследования и калибровочные точки (по три замера на уровень, с шумом).
    Каждый массив точек привязан к своему исследованию. Возвращает путь к файлу.
    """
    import random
    import compute  # внутри функции, чтобы не было кругового импорта

    init_sqlite(db_path)
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.executemany(
            "INSERT INTO Researchers (FullName, Workplace, Email) VALUES (?, ?, ?);",
            _DEMO_RESEARCHERS)
        cur.executemany(
            "INSERT INTO Reagents (Name, Manufacturer, Country, CatalogNumber) "
            "VALUES (?, ?, ?, ?);", _DEMO_REAGENTS)
        cur.executemany(
            "INSERT INTO Gene (Name, Description) VALUES (?, ?);", _DEMO_GENES)
        conn.commit()

        rid = cur.execute("SELECT ResearcherID FROM Researchers LIMIT 1;").fetchone()[0]
        genes = cur.execute("SELECT GeneID, Name FROM Gene;").fetchall()

        # Для каждого гена — отдельное исследование, к которому привязаны точки.
        study_of_gene = {}
        for gid, name in genes:
            cur.execute(
                "INSERT INTO Study (Title, ResearcherID, Date) VALUES (?, ?, ?);",
                (f"Калибровка гена {name} (2026)", rid, "2026-03-15"))
            study_of_gene[gid] = cur.lastrowid
        conn.commit()

        for gid, name in genes:
            profile = _DEMO_PROFILES[name]
            noise = _DEMO_NOISE[name]
            sid = study_of_gene[gid]
            for level in range(0, 101, 10):
                for _ in range(3):
                    obs = profile(level / 100.0) + random.uniform(-noise, noise)
                    obs = max(0.0, min(100.0, obs))
                    cur.execute(
                        "INSERT INTO Calibration (GeneID, StudyID, CalibrationLevel, "
                        "ObservedMethylation) VALUES (?, ?, ?, ?);",
                        (gid, sid, float(level), float(obs)))
        conn.commit()

    compute.recompute_all_genes(db_path)
    return db_path
