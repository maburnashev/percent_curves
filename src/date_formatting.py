import pandas as pd


def ConvertDates(dateSeries):
    # Сначала пробуем стандартный ISO формат
    try:
        return pd.to_datetime(dateSeries, format="%Y-%m-%d", errors="coerce")
    except:
        pass

    # Пробуем формат ДД.ММ.ГГГГ
    try:
        return pd.to_datetime(dateSeries, format="%d.%m.%Y", errors="coerce")
    except:
        pass

    # Если ничего не помогло, используем автоматическое определение
    return pd.to_datetime(dateSeries, errors="coerce")

def format_days(days):
    if days % 365 == 0:
        return f"{days // 365}Y"
    elif days % 30 == 0:
        return f"{days // 30}M"
    elif days % 7 == 0:
        return f"{days // 7}W"
    else:
        return f"{days}D"

def period_to_days(period):
    period = str(period).strip().upper()
    value = int(period[:-1])
    unit = period[-1]

    if unit == "D":
        return value
    if unit == "W":
        return value * 7
    if unit == "M":
        return value * 30
    if unit == "Y":
        return value * 365

    raise ValueError(f"Unsupported period format: {period}")