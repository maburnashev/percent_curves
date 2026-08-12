import pandas as pd
import os
from datetime import datetime, timedelta

from src.fut_data import GetFutData
from src.output import BuildTable, ApplyPerpetualRates, Compare
from src.calculations import MakeCalculations
from src.mapping import MapSecurities
from src.dividends import build


def main():
    date = datetime.now().date()
    while date.weekday() >= 5:  # 5 — суббота, 6 — воскресенье
        date -= timedelta(days=1)
    print(f"Дата {date}")
    os.makedirs(f"data_{date}", exist_ok=True)
    # os.makedirs(f"pics_{date}", exist_ok=True)

    ### получение данных по фьючерсам
    futData = GetFutData(date)
    futData.to_csv(f"data_{date}/futDataPreRaw_{date}.csv", index=False)
    print(f"получены данные по фьючерсам {date}")
    ### маппинг
    mapped = MapSecurities(futData, date)
    print(f"выполнен маппинг {date}")

    ### загрузка объявленных дивидендов
    build()
    announced_dividends = pd.read_excel(f"data_{date}/df_dividends_announced.xlsx")

    ### расчет вмененных ставок
    iFutData = MakeCalculations(futData, mapped, date, announced_dividends)
    iFutData.to_csv(f"data_{date}/futDataRaw_{date}.csv", index=False)
    iFutData = iFutData[["TRADEDATE", "ASSETCODE", 't', 'R']]
    print(f"выполнен расчет вмененных ставок {date}")

    ### приведение к правильному виду
    standardTable = BuildTable(iFutData)
    ### работа с вечными фьючерсами
    standardTable = ApplyPerpetualRates(standardTable)
    standardTable.to_csv(f"data_{date}/futRates_{date}.csv", index=False)
    print(f"выполнены интерполяция и экстраполяция {date}")

    ### проверка
    compare = Compare(date)
    compare.to_excel(f"data_{date}/finalCompare_{date}.xlsx", index=False)
    print(f"выполнена проверка {date}")

    ### визуализация
    # PlotRateCurve(standardTable, "BRM", f"pics/futDataStandardCurve_{date}.png", True)
    # print(f"выполнена визуализация {date}")

if __name__ == "__main__":
    main()
