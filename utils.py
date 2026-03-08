# utils.py
import re
import csv
from pathlib import Path

def parse_numbers_from_text(text):
    nums = re.findall(r'[-+]?\d*\.\d+|\d+', text)
    return [float(x) for x in nums]

def parse_file(filepath):
    """
    Попробует распознать формат файла:
    - .txt: извлекает все числа (возвращает список)
    - .csv: пытается прочесть колонку 'observed' или взять первую числовую колонку
    Возвращает список float (одномерный список наблюдений).
    """
    p = Path(filepath)
    if not p.exists():
        return []
    suffix = p.suffix.lower()
    text = p.read_text(encoding='utf-8', errors='ignore')
    if suffix in ('.txt', '.log', '.out'):
        return parse_numbers_from_text(text)
    if suffix == '.csv':
        with p.open(newline='', encoding='utf-8', errors='ignore') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if not rows:
                return []
            
            # Нормализация имен колонок для поиска
            field_map = {name.lower().strip(): name for name in (reader.fieldnames or [])}
            
            # Поиск колонки с наблюдениями
            obs_col = None
            for candidate in ['observed', 'measured', 'value', 'methylation', 'y']:
                if candidate in field_map:
                    obs_col = field_map[candidate]
                    break
            
            if obs_col:
                out = []
                for r in rows:
                    val = r.get(obs_col)
                    if val not in (None, ''):
                        try:
                            out.append(float(val))
                        except Exception:
                            pass
                return out
            
            # иначе пробуем найти первую числовую колонку
            for field in reader.fieldnames:
                try:
                    test = [float(r[field]) for r in rows if r.get(field) not in (None,'')]
                    if test:
                        return test
                except Exception:
                    continue
            return []
    # fallback
    return parse_numbers_from_text(text)

def parse_pairs(filepath):
    """
    Извлекает пары (истинное, измеренное) для массового импорта.
    Возвращает список кортежей (true_val, observed_val).
    """
    p = Path(filepath)
    if not p.exists():
        return []
    suffix = p.suffix.lower()
    
    if suffix == '.csv':
        with p.open(newline='', encoding='utf-8', errors='ignore') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if not rows:
                return []
            
            fieldnames = reader.fieldnames or []
            if not fieldnames:
                return []

            # Попытка найти колонки по именам
            fmap = {n.lower().strip(): n for n in fieldnames}
            
            true_col = None
            for c in ['true', 'actual', 'level', 'calibration', 'x']:
                if c in fmap:
                    true_col = fmap[c]; break
            
            obs_col = None
            for c in ['observed', 'measured', 'value', 'methylation', 'y']:
                if c in fmap:
                    obs_col = fmap[c]; break
            
            # Если нашли обе специфичные колонки
            if true_col and obs_col and true_col != obs_col:
                pairs = []
                for r in rows:
                    try:
                        tv = float(r[true_col])
                        ov = float(r[obs_col])
                        pairs.append((tv, ov))
                    except Exception:
                        pass
                if pairs:
                    return pairs

            # Иначе ищем две первые числовые колонки
            numeric_cols = []
            for col in fieldnames:
                try:
                    # Проверяем, содержит ли колонка числа (хотя бы 50% валидных)
                    valid_count = 0
                    total_count = 0
                    for r in rows[:50]: # check first 50 rows
                        val = r.get(col)
                        if val not in (None, ''):
                            total_count += 1
                            try:
                                float(val)
                                valid_count += 1
                            except:
                                pass
                    if total_count > 0 and (valid_count / total_count) > 0.5:
                        numeric_cols.append(col)
                except:
                    pass
            
            if len(numeric_cols) >= 2:
                # Предполагаем порядок: X (True), Y (Observed)
                c1, c2 = numeric_cols[0], numeric_cols[1]
                pairs = []
                for r in rows:
                    try:
                        v1 = float(r[c1])
                        v2 = float(r[c2])
                        pairs.append((v1, v2))
                    except:
                        pass
                return pairs

    # Fallback для txt или если csv не распарсился по колонкам
    text = p.read_text(encoding='utf-8', errors='ignore')
    nums = parse_numbers_from_text(text)
    pairs = []
    for i in range(0, len(nums)-1, 2):
        pairs.append((nums[i], nums[i+1]))
    return pairs

def format_bool(b):
    return "Да" if b else "Нет"
