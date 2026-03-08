# seed_db.py
"""
Скрипт для создания тестовой БД и наполнения реалистичными данными для демонстрации.
Запуск: python seed_db.py
"""
import db
import sqlite3
import random
import compute

def seed(db_path="sample_db.sqlite3"):
    db.init_sqlite(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # 1. Добавляем исследователей
    researchers = [
        ("Иванов И.И.", "Институт Генетики", "ivanov@example.com"),
        ("Петрова А.С.", "Лаборатория Биоинформатики", "petrova@example.com")
    ]
    for r in researchers:
        cur.execute("INSERT INTO Researchers (FullName, Workplace, Email) VALUES (?, ?, ?);", r)
    
    # 2. Добавляем реактивы
    reagents = [
        ("EpiTect Bisulfite Kit", "Qiagen", "Germany", "59104"),
        ("EZ DNA Methylation Kit", "Zymo Research", "USA", "D5001")
    ]
    for r in reagents:
        cur.execute("INSERT INTO Reagents (Name, Manufacturer, Country, CatalogNumber) VALUES (?, ?, ?, ?);", r)

    # 3. Добавляем гены
    genes = [
        ("MGMT", "O-6-methylguanine-DNA methyltransferase"),
        ("MLH1", "MutL homolog 1"),
        ("CDKN2A", "Cyclin-dependent kinase inhibitor 2A")
    ]
    for name, desc in genes:
        cur.execute("INSERT INTO Gene (Name, Description) VALUES (?, ?);", (name, desc))
    conn.commit()

    # 4. Добавляем калибровочные данные
    cur.execute("SELECT GeneID, Name FROM Gene;")
    genes_db = cur.fetchall()
    
    for gid, name in genes_db:
        if name == "MGMT":
            # Кубическая зависимость (S-образная кривая)
            for lvl in range(0, 101, 10):
                for _ in range(3):
                    # Имитация S-образной кривой с шумом
                    x = lvl / 100.0
                    y = 3 * (x**2) - 2 * (x**3) # Smoothstep
                    observed = y * 100.0 + random.uniform(-3, 3)
                    observed = max(0.0, min(100.0, observed))
                    cur.execute("INSERT INTO Calibration (GeneID, CalibrationLevel, ObservedMethylation) VALUES (?, ?, ?);", (gid, float(lvl), float(observed)))
        elif name == "MLH1":
            # Гиперболическая/логарифмическая зависимость (быстрый рост в начале)
            for lvl in range(0, 101, 10):
                for _ in range(3):
                    x = lvl / 100.0
                    y = x ** 0.5 # Выпуклая кривая
                    observed = y * 100.0 + random.uniform(-4, 4)
                    observed = max(0.0, min(100.0, observed))
                    cur.execute("INSERT INTO Calibration (GeneID, CalibrationLevel, ObservedMethylation) VALUES (?, ?, ?);", (gid, float(lvl), float(observed)))
        else:
            # Линейная зависимость
            for lvl in range(0, 101, 10):
                for _ in range(3):
                    observed = lvl + random.uniform(-5, 5)
                    observed = max(0.0, min(100.0, observed))
                    cur.execute("INSERT INTO Calibration (GeneID, CalibrationLevel, ObservedMethylation) VALUES (?, ?, ?);", (gid, float(lvl), float(observed)))

    conn.commit()
    conn.close()
    
    # 5. Рассчитываем аппроксимации для всех генов
    for gid, _ in genes_db:
        compute.recompute_averages_for_gene(db_path, gid)
        compute.compute_and_store_approximations_for_gene(db_path, gid)

    print(f"Sample DB created and populated at {db_path}")

if __name__ == "__main__":
    seed()
