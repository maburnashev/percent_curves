import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import requests
from urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

from src.date_formatting import format_days, period_to_days
from src.extra_data import sdfi_ruonia_standart

perpetual_rate_sources = {
    "USDRUBF": "Si",
    "USDRUB_TOM": "Si",
    "USDRUBTOM": "Si",
    "EURRUBF": "Eu",
    "EURRUB_TOM": "Eu",
    "EURRUBTOM": "Eu",
    "CNYRUBF": "CNY",
    "CNYRUB_TOM": "CNY",
    "CNYRUBTOM": "CNY",
    "IMOEX": "MXI",
    "RGBIF": "RGBI",
    "GLDRUBF": "GOLD",
    "GLDRUBTOM": "GOLD",
    "SLVRUBF": "SILV",
    "SLVRUBTOM": "SILV",
    "SBERF": "SBRF",
    "GAZPF": "GAZR",
    "QQQF": "NASD",
    "SP500F": "SPYF"
}

def PlotRateCurve(standardTable, assetCode=None, savePath="futRateCurve.png", show=False):
    requiredColumns = {"Date", "BC", "KEY_PERIOD", "r"}
    missingColumns = requiredColumns - set(standardTable.columns)
    if missingColumns:
        raise ValueError(f"standardTable must contain columns: {sorted(missingColumns)}")

    plotData = standardTable.copy()
    plotData["days"] = plotData["KEY_PERIOD"].apply(period_to_days)
    plotData["r"] = pd.to_numeric(plotData["r"], errors="coerce")
    plotData = plotData.dropna(subset=["days", "r"])

    if assetCode is not None:
        plotData = plotData[plotData["BC"] == assetCode]

    if plotData.empty:
        raise ValueError("No data to plot after filtering.")

    fig, ax = plt.subplots(figsize=(12, 7))

    groupedData = list(plotData.groupby("BC", sort=True))
    for bc, group in groupedData:
        group = group.sort_values("days")
        ax.plot(
            group["days"],
            group["r"] * 100,
            marker="o",
            linewidth=1.8,
            markersize=4,
            label=bc,
        )

    ax.set_title("Futures Interest Rate Curve")
    ax.set_xlabel("Days")
    ax.set_ylabel("Rate, %")
    ax.grid(True, alpha=0.3)
    if len(groupedData) <= 20:
        ax.legend(title="BC")
    fig.tight_layout()

    if savePath:
        fig.savefig(savePath, dpi=150)

    if show:
        plt.show()
    else:
        plt.close(fig)

    return fig

def BuildRows(group):
    standardDays = [1, 7, 14, 30, 60, 90, 180, 270, 365, 730, 1095, 1460, 1825, 2190, 2555, 2920, 3285, 3650]
    assetCode = group["ASSETCODE"].iloc[0]
    tradeDate = group["TRADEDATE"].iloc[0]

    curve = (
        group[["t", "R"]]
        .dropna()
        .sort_values("t")
        .drop_duplicates(subset="t", keep="first")
    )

    rows = []

    if curve.empty:
        for day in standardDays:
            rows.append({
                "tradedate": tradeDate,
                "assetcode": assetCode,
                "t": day,
                "r": np.nan,
            })
        return pd.DataFrame(rows)

    existingDays = curve["t"].to_numpy(dtype=float)
    existingRates = curve["R"].to_numpy(dtype=float)

    for day in standardDays:
        if len(existingDays) == 1:
            rate = existingRates[0]
        elif day < existingDays[0]:
            rate = existingRates[0]
        elif day > existingDays[-1]:
            rate = existingRates[-1]
        else:
            rate = np.interp(day, existingDays, existingRates)

        rows.append({
            "tradedate": tradeDate,
            "assetcode": assetCode,
            "t": day,
            "r": rate,
        })

    return pd.DataFrame(rows)

def BuildTable(futData):
    rows = [
        BuildRows(group)
        for _, group in futData.groupby("ASSETCODE", sort=False)
    ]

    if not rows:
        return pd.DataFrame(columns=["Date", "cl_period", "BC", "KEY_PERIOD", "r"])
    table = pd.concat(rows, ignore_index=True)
    # промежуточная таблица
    # table.to_csv("futDataR.csv", index=False)
    res = pd.DataFrame()
    res["Date"] = pd.to_datetime(table["tradedate"]).dt.date
    res["cl_period"] = "CL"
    res['KEY_PERIOD'] = table["t"].apply(format_days).astype(str)
    res["BC"] = table["assetcode"]
    res["r"] = table["r"]
    ruon_std = sdfi_ruonia_standart()
    res = res.merge(
        ruon_std,
        on="KEY_PERIOD",
        how="left"
    )
    tmp = pd.read_csv("Astra_template.csv", sep=';')
    for column in tmp.columns:
        if column not in res.columns:
            res[column] = np.nan
    res = res[tmp.columns]
    return res.sort_values(["Date", "BC"]).reset_index(drop=True)

def ApplyPerpetualRates(standardTable):
    res = standardTable.copy()
    replacementRows = []
    replacedCodes = []

    for targetCode, sourceCode in perpetual_rate_sources.items():
        sourceRows = res[res["BC"] == sourceCode]
        if sourceRows.empty:
            continue

        targetRows = res[res["BC"] == targetCode]
        if targetRows.empty:
            continue

        copiedRows = sourceRows.copy()
        copiedRows["BC"] = targetCode
        replacementRows.append(copiedRows)
        replacedCodes.append(targetCode)

    if not replacementRows:
        return res

    res = res[~res["BC"].isin(replacedCodes)]
    res = pd.DataFrame(pd.concat([res, *replacementRows], ignore_index=True))
    res["r"] = np.where( # с фьючерсом на индекс волатильности так нельзя
        res["BC"] == "RVI",
        0,
        res["r"]
    )
    ### допущение №1
    res["r"] = res["r"].fillna(0)
    res["R2_SPOT"] = res["R_SPOT"] - res["r"]
    return res.sort_values(["Date", "BC"]).reset_index(drop=True)

def Compare(trade_date):
    url = "https://iss.moex.com/iss/rms/engines/futures/objects/staticparamskeyterm.json"
    params = {
        "date": trade_date,
    }
    response = requests.get(url, params=params, timeout=20)
    response.raise_for_status()
    rows = []
    start = 0

    while True:
        params = {
            "start": start,
        }
        if trade_date is not None:
            params["date"] = trade_date

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        load = response.json()

        block = load["staticparamskeyterm"]
        df_part = pd.DataFrame(block["data"], columns=block["columns"])
        rows.append(df_part)

        cursor = load["staticparamskeyterm.cursor"]["data"][0]
        _, total, page_size = cursor

        start += page_size
        if start >= total or df_part.empty:
            break

    df = pd.DataFrame(pd.concat(rows, ignore_index=True))

    df["tradedate"] = pd.to_datetime(df["tradedate"], errors="coerce")
    df["updatetime"] = pd.to_datetime(df["updatetime"], errors="coerce")

    numeric_cols = [
        "t", "r", "ir", "vr", "vvr", "vrspot", "vvrspot",
        "r_spot", "r2_spot", "ir_spot", "ir2_spot",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    #
    other = df[['tradedate', 'assetcode', 'r']].copy()
    other['t'] = df['t'].apply(format_days).copy()
    mine = pd.read_excel(f'data_{trade_date}/futRates_{trade_date}.xlsx')
    mine = mine[['Date', 'BC', 'r', 'KEY_PERIOD']]
    mine.columns = ['tradedate', 'assetcode', 'r', 't']
    mine["tradedate"] = pd.to_datetime(mine["tradedate"], errors="coerce")

    compare = other.merge(
        mine[["assetcode", "t", "r"]],
        on=["assetcode", "t"],
        how="outer",
    )
    compare = compare[["tradedate", "assetcode", "t", "r_x", "r_y"]]
    compare.columns = ["tradedate", "assetcode", "t", "r_moex", "r_mine"]
    compare["diff"] = np.where(
        compare["r_mine"].notnull() & compare["r_moex"].notnull() & compare["r_moex"] != 0,
        pd.Series(pd.to_numeric(compare["r_mine"] / compare["r_moex"] - 1)).map('{:.2%}'.format),
        np.nan
    )
    return compare.sort_values(["tradedate", "assetcode"]).reset_index(drop=True)
