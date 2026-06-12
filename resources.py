"""
Локализованные строки.

Все русские заголовки таблиц/колонок вынесены сюда, чтобы интерфейс и логика
не были перемешаны со строковыми константами.
"""

APP_TITLE = "Менеджер метилирования"

# Русские названия таблиц для выпадающего списка в редакторе БД.
TABLE_LABELS = {
    "Gene": "Гены",
    "Researchers": "Исследователи",
    "Publications": "Публикации",
    "Reagents": "Реактивы",
    "Study": "Исследования",
    "Calibration": "Калибровочные измерения",
    "Avg_Calibration": "Усреднённые измерения",
    "Primers": "Праймеры",
    "AmplificationStep": "Этапы амплификации",
    "Approximation": "Аппроксимации",
}

# Подписи столбцов; берутся по имени поля в БД.
COLUMN_NAMES_RU = {
    "GeneID": "ID гена",
    "Name": "Название",
    "Description": "Описание",
    "ResearcherID": "ID исследователя",
    "FullName": "ФИО",
    "Workplace": "Место работы",
    "Email": "Email",
    "PublicationID": "ID публикации",
    "Title": "Заголовок",
    "Journal": "Журнал",
    "Volume": "Том",
    "Year": "Год",
    "Pages": "Страниц",
    "ReagentID": "ID реактива",
    "Manufacturer": "Производитель",
    "Country": "Страна",
    "CatalogNumber": "Каталожный номер",
    "StudyID": "ID исследования",
    "Date": "Дата",
    "CalibrationID": "ID калибровки",
    "CalibrationLevel": "Истинное (%)",
    "ObservedMethylation": "Измеренное (%)",
    "AvgID": "ID усреднения",
    "AvgObservedMethylation": "Среднее измеренное (%)",
    "CountMeasurements": "Кол-во замеров",
    "PrimerID": "ID праймера",
    "Sequence": "Последовательность",
    "GeneCopySize": "Размер копии",
    "CpGPositions": "CpG-позиций",
    "AmplificationID": "ID этапа",
    "StepNumber": "Номер шага",
    "Temperature": "Температура (°C)",
    "DurationSeconds": "Длительность (с)",
    "ApproximationID": "ID аппроксимации",
    "FunctionType": "Тип функции",
    "Coefficients": "Коэффициенты",
    "StdDeviation": "σ (СКО)",
    "RelativeError": "ε (отн. ошибка)",
    "AdditionalMetrics": "Доп. метрики",
    "CreatedAt": "Дата расчёта",
    "MeasurementDate": "Дата измерения",
    "Notes": "Заметки",
}

# Человекочитаемые названия типов аппроксимаций.
APPROX_DISPLAY = {
    "кубическая": "Кубическая (3-й порядок)",
    "гипербола_сдвиг": "Гипербола (со сдвигом)",
    "комбинированная_сдвиг": "Комбинированная (со сдвигом)",
}
