# db.py
import sqlite3
from pathlib import Path
from PySide6.QtSql import QSqlDatabase
import shutil

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
CREATE INDEX IF NOT EXISTS idx_avg_cal_gene ON Avg_Calibration(GeneID);
CREATE INDEX IF NOT EXISTS idx_approx_gene ON Approximation(GeneID);
"""

DEFAULT_DB = str(Path.cwd() / "methyl_data_full.sqlite3")

def init_sqlite(db_path=DEFAULT_DB):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.execute("PRAGMA foreign_keys = ON;")
    cur = conn.cursor()
    cur.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
    return db_path

def open_qt_sql(db_path=DEFAULT_DB, connection_name="methyl_conn"):
    """
    Обёртка для QSqlDatabase; если connection_name уже создан — закрываем и пересоздаём.
    Возвращает объект QSqlDatabase.
    """
    if QSqlDatabase.contains(connection_name):
        db_old = QSqlDatabase.database(connection_name)
        try:
            if db_old.isOpen():
                db_old.close()
        except Exception:
            pass
        QSqlDatabase.removeDatabase(connection_name)

    db = QSqlDatabase.addDatabase("QSQLITE", connection_name)
    db.setDatabaseName(str(db_path))
    ok = db.open()
    if not ok:
        raise RuntimeError("Не удалось открыть SQLite через QSqlDatabase. Проверьте поддержку QSQLITE.")
    return db

def execute_sql(sql, params=(), db_path=DEFAULT_DB):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.commit()
    conn.close()
    return rows

def fetchall(sql, params=(), db_path=DEFAULT_DB):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return rows

def export_db(db_path=DEFAULT_DB, dest_path=None):
    """
    Копирует sqlite-файл в dest_path.
    """
    if dest_path is None:
        raise ValueError("dest_path is required")
    src = Path(db_path)
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # use shutil.copy to copy file
    shutil.copy(str(src), str(dest))
    return str(dest)
