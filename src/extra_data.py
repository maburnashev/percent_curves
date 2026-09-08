import pandas as pd
import numpy as np
import requests
import json
from urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

from src.date_formatting import format_days

historical_dividends_start_date = pd.Timestamp("2014-01-01")

def get_historical_dividends():
    shares_mapped = pd.read_excel("dividends/shares_mapping.xlsx")
    pure_isins = shares_mapped[shares_mapped["STOCKS_FULL_ID"] != 0]["ISIN"]
    res = []
    for isin in pure_isins:
        try:
            tmp = pd.read_excel(f"dividends/{isin}.xlsx")
            res.append(tmp)
        except FileNotFoundError:
            pass
    df = pd.DataFrame(pd.concat(res))
    df["Тикер"] = df["Тикер"].str.split(",").str[0].str.strip()
    try:
        df.to_excel("dividends/shares_with_futures.xlsx", index=False)
    except PermissionError:
        pass
    return df

### раскомментировать 4 строки и закомментироватьь with open(...) ...
def sdfi_ruonia():
    url = "https://iss.moex.com/iss/sdfi/curves/RUB-DFA-CSARUB.json"
    response = requests.get(url, verify=False)
    response.raise_for_status()
    data = response.json()
    # with open('data.json') as f:
    #     data = json.load(f)

    df = pd.DataFrame(
        data=data['curves']['data'],
        columns=data['curves']['columns'],
    )
    max_time = max(df["calctime"])
    df = pd.DataFrame(df[(df["calctime"] == max_time)])
    df["days"] = pd.to_numeric(df["tenor"].str.rstrip("D"))
    df["rate"] = 1 / df["value"] - 1
    df["ruonia_year"] = (1 + df["rate"]) ** (365 / df["days"]) - 1
    return df.sort_values(["days"])

def sdfi_ruonia_standart():
    tenors = [1, 7, 14, 30, 60, 90, 180, 270, 365, 730, 1095, 1460, 1825, 2190, 2555, 2920, 3285, 3650]
    df = sdfi_ruonia()
    lst = []
    for tenor in tenors:
        df["delta"] = abs(df["days"] - tenor)
        df["time"] = tenor
        min_diff = min(df["delta"])
        mask = df["delta"] == min_diff
        lst.append(df[mask])
    df_final = pd.DataFrame(pd.concat(lst))
    df_final["KEY_PERIOD"] = df_final["time"].apply(format_days)
    df_final["R_SPOT"] = df_final["ruonia_year"].copy()
    return df_final[["KEY_PERIOD", "R_SPOT"]]

# def get_ruonia():
#     # теперь получаем среднее значение ruonia для каждого года для обратного дисконтирования
#     ruonia = pd.read_excel("dividends/RC_F11_01_2010_T05_08_2026.xlsx") # взято с сайта цб
#     ruonia["год"] = ruonia["DT"].dt.year
#     ruonia["ставка"] = ruonia["ruo"] / 100
#     ruonia_clean = ruonia.dropna(subset=["ставка", "vol"]).copy()
#
#     ruonia_clean["weighted_rate"] = ruonia_clean["ставка"] * ruonia_clean["vol"]
#
#     annual_ruonia = (
#         ruonia_clean
#         .groupby("год", as_index=False)
#         .agg(
#             weighted_rate_sum=("weighted_rate", "sum"),
#             volume_sum=("vol", "sum")
#         )
#     )
#
#     annual_ruonia["годовая ставка"] = (
#             annual_ruonia["weighted_rate_sum"] / annual_ruonia["volume_sum"]
#     )
#     base_years = pd.DataFrame({
#         "год": range(2000, 2010),
#         "годовая ставка": 0.04
#     })
#
#     annual_ruonia = (
#         pd.concat([base_years, annual_ruonia], ignore_index=True)
#         .sort_values("год")
#         .reset_index(drop=True)
#     )
#
#     annual_ruonia = annual_ruonia[["год", "годовая ставка"]]
#     annual_ruonia["годовая ставка"] = np.where(
#         (annual_ruonia["год"] == 2026),
#         (1 + annual_ruonia["годовая ставка"]) ** (7 / 12) - 1,
#         annual_ruonia["годовая ставка"]
#     )
#     annual_ruonia["накопленная ставка"] = (1 + annual_ruonia["годовая ставка"]).cumprod() - 1
#     annual_ruonia["коэффициент накопления"] = (1 + annual_ruonia["накопленная ставка"])
#     coef_2026 = annual_ruonia[annual_ruonia["год"] == 2026]["коэффициент накопления"].iloc[0]
#     annual_ruonia["коэффициент индексации к 2026"] = (
#             coef_2026 / annual_ruonia["коэффициент накопления"]
#     )
#     return annual_ruonia

def get_dividends():
    shares_newer = get_historical_dividends()
    # annual_ruonia = get_ruonia()
    shares_newer["дивидендная дата"] = (
        pd.to_datetime(shares_newer["Экс-дивидендная дата"], errors="coerce")
        .combine_first(pd.to_datetime(shares_newer["Закрытие реестра"], errors="coerce"))
    )
    shares_newer = shares_newer[
        shares_newer["дивидендная дата"] >= historical_dividends_start_date
    ].copy()
    shares_newer["год закрытия реестра"] = pd.to_datetime(shares_newer["Закрытие реестра"]).dt.year
    # shares_newer = shares_newer.merge(
    #     annual_ruonia[["год", "коэффициент индексации к 2026"]],
    #     left_on="год закрытия реестра",
    #     right_on="год",
    #     how="left"
    # )

    # shares_newer["Дивиденд индексированный к 2026"] = (
    #         shares_newer["Дивиденд"] * shares_newer["коэффициент индексации к 2026"]
    # )


    def build_dividend_calendar(group):
        month_counts = group["дивидендный месяц"].value_counts()
        months = list(month_counts.index[:2])

        first_month = months[0] if len(months) >= 1 else np.nan
        second_month = months[1] if len(months) >= 2 else np.nan

        first_day = np.nan
        if pd.notna(first_month):
            first_day = int(round(group.loc[group["дивидендный месяц"] == first_month, "дивидендный день"].mean()))

        second_day = np.nan
        if pd.notna(second_month):
            second_day = int(round(group.loc[group["дивидендный месяц"] == second_month, "дивидендный день"].mean()))

        return pd.Series({
            "самый_частый_месяц_дивиденда": first_month,
            "самый_частый_день_дивиденда": first_day,
            "второй_самый_частый_месяц_дивиденда": second_month,
            "второй_самый_частый_день_дивиденда": second_day,
        })

    planned_dividends = shares_newer[
        (shares_newer["Дивиденд"] > 0)
        & shares_newer["дивидендная дата"].notna()
    ].copy()
    planned_dividends["дивидендный месяц"] = planned_dividends["дивидендная дата"].dt.month
    planned_dividends["дивидендный день"] = planned_dividends["дивидендная дата"].dt.day

    dividend_calendar = (
        planned_dividends
        .groupby("Тикер", as_index=False)
        .apply(build_dividend_calendar, include_groups=False)
    )
    shares_newer = shares_newer.merge(dividend_calendar, on="Тикер", how="left")

    return shares_newer[[
        "Тикер",
        "Дивиденд",
        "Валюта",
        "дивидендная дата",
        "самый_частый_месяц_дивиденда",
        "самый_частый_день_дивиденда",
        "второй_самый_частый_месяц_дивиденда",
        "второй_самый_частый_день_дивиденда",
    ]]

def get_currency_rates(trade_date):
    url = "https://iss.moex.com/iss/statistics/engines/currency/markets/selt/rates.json"
    params = {
        "date": trade_date,
    }
    response = requests.get(url, params=params, verify=False)
    response.raise_for_status()
    data = response.json()
    # print(data["cbrf"])
    df = pd.DataFrame(
        data["cbrf"]["data"],
        columns=data["cbrf"]["columns"]
    )
    df.transpose()
    usd_rub = df["CBRF_USD_LAST"].iloc[0]
    eur_rub = df["CBRF_EUR_LAST"].iloc[0]
    return {
        "usd_rub": usd_rub,
        "eur_rub": eur_rub
    }

def get_avg_dividends():
    shares_final = get_dividends()
    currency_rate_cache = {}

    def convert_dividend_to_rub(row):
        currency = str(row["Валюта"]).strip().upper()
        dividend = row["Дивиденд"]

        if currency == "RUB":
            return dividend
        if currency not in ["USD", "EUR"] or pd.isna(row["дивидендная дата"]):
            return np.nan

        rate_date = pd.to_datetime(row["дивидендная дата"]).date()
        if rate_date not in currency_rate_cache:
            currency_rate_cache[rate_date] = get_currency_rates(rate_date)

        rate_key = f"{currency.lower()}_rub"
        return dividend * currency_rate_cache[rate_date][rate_key]

    shares_final["Дивиденд_RUB"] = shares_final.apply(convert_dividend_to_rub, axis=1)
    avg_dividends = (
        shares_final.groupby("Тикер", as_index=False)
        .agg(
            средний_дивиденд=("Дивиденд_RUB", "mean"),
            # средний_дивиденд_индексированный=("Дивиденд индексированный к 2026", "mean"),
            самый_частый_месяц_дивиденда=("самый_частый_месяц_дивиденда", "first"),
            самый_частый_день_дивиденда=("самый_частый_день_дивиденда", "first"),
            второй_самый_частый_месяц_дивиденда=("второй_самый_частый_месяц_дивиденда", "first"),
            второй_самый_частый_день_дивиденда=("второй_самый_частый_день_дивиденда", "first"),
        )
    )
    return avg_dividends

def get_g_curve(tradedate):
    url = "https://iss.moex.com/iss/engines/stock/zcyc.json"

    params = {
        "date": tradedate,
        "iss.only": "yearyields",
    }

    response = requests.get(url, params=params, timeout=30, verify=False)
    response.raise_for_status()
    data = response.json()

    curve = pd.DataFrame(
        data["yearyields"]["data"],
        columns=data["yearyields"]["columns"],
    )
    return curve[["period", "value"]]
