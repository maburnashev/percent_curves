import pandas as pd
import numpy as np
import requests
from urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

from src.date_formatting import ConvertDates
from src.extra_data import get_avg_dividends, get_g_curve
from src.extra_data import sdfi_ruonia


force_future_is_spot_assets = ["RGBI", "RTS"]
perpetual_futures = ['USDRUBF', 'EURRUBF', 'CNYRUBF', 'IMOEXF', 'RGBIF', 'GLDRUBF', 'SLVRUBF', 'SBERF', 'GAZPF', 'USDRUB_TOM', 'EURRUB_TOM', 'CNYRUB_TOM', 'SP500F', 'QQQF']

def get_future_price(futData):
    future_price = np.where(
        futData["ASSETCODE"] == "NASD",
        futData["SETTLEPRICE"] / 41,
        np.where(
            futData["is_not_rub"] == 1,
            futData["SETTLEPRICE"],
            (futData["SETTLEPRICE"] * futData["STEPPRICE"]) / (futData["LOTVOLUME"] * futData["MINSTEP"])
        )
    )
    return np.where(
        futData["ASSETCODE"] == "MXI",
        future_price / 10,
        np.where(
            futData["ASSETCODE"].isin(["MIX", "RGBI"]),
            future_price / 100,
            future_price
        )
    )


def future_is_spot(futData):
    idxMinDays = futData.groupby("ASSETCODE")["DaysToExp"].idxmin()
    nearestContracts = futData.loc[idxMinDays, ["ASSETCODE", "SECID", "SETTLEPRICE", "DaysToExp"]].copy()
    nearestContracts.columns = ["ASSETCODE", "SpotCode", "SpotPrice", "SpotDaysToExp"]
    futData = futData.merge(nearestContracts, on="ASSETCODE", how="left")

    futData["DeltaDaysToExp"] = futData["DaysToExp"] - futData["SpotDaysToExp"]
    futData["t"] = futData["DeltaDaysToExp"]

    futData["R"] = np.where(
        futData["t"] != 0,
        np.log(futData["SETTLEPRICE"] / futData["SpotPrice"]) / futData["t"] * 365,
        np.nan  # Для ближнего контракта R не определен (во втором случае)
    )
    futData["is_announced"] = 0
    futData["most_common_day"] = np.nan
    futData["most_common_month"] = np.nan
    futData["second_most_common_day"] = np.nan
    futData["second_most_common_month"] = np.nan
    futData["div_size"] = np.nan
    futData["settlementprice_theory"] = np.nan
    futData["is_div_implied"] = 0
    futData["F"] = np.nan
    futData["discounted_div_size"] = np.nan
    futData["t1_div_rates"] = np.nan
    futData["days_to_div"] = np.nan
    return futData[[
        "TRADEDATE",
        "ASSETCODE",
        't',
        'R',
        "SETTLEPRICE",
        "underlying_asset",
        "SpotPrice",
        "most_common_day",
        "most_common_month",
        "second_most_common_day",
        "second_most_common_month",
        "div_size",
        "days_to_div",
        "settlementprice_theory",
        "is_div_implied",
        "F",
        "t1_div_rates",
        "discounted_div_size",
        "is_announced",
        "asset_type",
        "is_not_rub"
    ]]

def perpetual_future_is_spot(futData):
    futData = futData[futData["perpetual_is_spot"] == 1].copy()
    result_columns = [
        "TRADEDATE",
        "ASSETCODE",
        't',
        'R',
        "SETTLEPRICE",
        "underlying_asset",
        "SpotPrice",
        "most_common_day",
        "most_common_month",
        "second_most_common_day",
        "second_most_common_month",
        "div_size",
        "days_to_div",
        "settlementprice_theory",
        "is_div_implied",
        "F",
        "t1_div_rates",
        "discounted_div_size",
        "is_announced",
        "asset_type",
        "is_not_rub"
    ]
    if futData.empty:
        for column in result_columns:
            if column not in futData.columns:
                futData[column] = np.nan
        return futData[result_columns]

    base_codes = futData["count_with"].dropna().unique()
    spot_prices = (
        futData[futData["ASSETCODE"].isin(base_codes)]
        .sort_values(["ASSETCODE", "DaysToExp"])
        .drop_duplicates(subset=["ASSETCODE"], keep="first")
        .copy()
    )
    spot_prices["SpotPrice"] = get_future_price(spot_prices)
    spot_prices = (
        spot_prices[["ASSETCODE", "SECID", "DaysToExp", "SpotPrice"]]
        .rename(columns={
            "ASSETCODE": "count_with",
            "SECID": "SpotCode",
            "DaysToExp": "SpotDaysToExp",
        })
    )

    futData = futData.merge(
        spot_prices[["count_with", "SpotCode", "SpotPrice", "SpotDaysToExp"]],
        on="count_with",
        how="left",
    )
    futData["F"] = get_future_price(futData)
    futData["t"] = np.where(
        futData["ASSETCODE"] == futData["count_with"],
        0,
        futData["DaysToExp"],
    )
    futData["R"] = np.where(
        (futData["t"] > 0) & (futData["F"] > 0) & (futData["SpotPrice"] > 0),
        365 * np.log(futData["F"] / futData["SpotPrice"]) / futData["t"],
        np.nan,
    )
    futData["is_announced"] = 0
    futData["most_common_day"] = np.nan
    futData["most_common_month"] = np.nan
    futData["second_most_common_day"] = np.nan
    futData["second_most_common_month"] = np.nan
    futData["div_size"] = np.nan
    futData["settlementprice_theory"] = np.nan
    futData["is_div_implied"] = 0
    futData["discounted_div_size"] = np.nan
    futData["t1_div_rates"] = np.nan
    futData["days_to_div"] = np.nan

    return futData[result_columns]

def asset_is_spot(futData, tradedate, asset_type: str, announced_dividends=None):
    trade_date = pd.to_datetime(tradedate)
    column = "LAST"
    # column = "LCLOSEPRICE"
    base_url = f"https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/"
    if asset_type == "index":
        base_url = f"https://iss.moex.com/iss/engines/stock/markets/index/securities/"
        column = "LASTVALUE"
        # column = "CURRENTVALUE "

    def get_nearest_g_curve_rates(days_to_exp):
        curve = get_g_curve(tradedate).copy()
        curve["period"] = pd.to_numeric(curve["period"], errors="coerce")
        curve["value"] = pd.to_numeric(curve["value"], errors="coerce")
        curve = curve.dropna(subset=["period", "value"])

        if curve.empty:
            return pd.Series(np.nan, index=days_to_exp.index)

        curve["rate"] = curve["value"] / 100

        rates = []
        for days in days_to_exp:
            if pd.isna(days):
                rates.append(np.nan)
                continue

            years_to_exp = days / 365
            idx = (curve["period"] - years_to_exp).abs().idxmin()
            rates.append(curve.loc[idx, "rate"])

        return pd.Series(rates, index=days_to_exp.index)

    def get_stock_market_price(code: str):
        if pd.isna(code) or str(code).strip() == "":
            return np.nan
        url = base_url + f"{code}.json"
        params = {
            "date": tradedate,
        }
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
        except (requests.exceptions.RequestException, ValueError) as error:
            print(f"Не удалось получить спот для {code}: {error}")
            return np.nan

        marketdata = pd.DataFrame(
            data["marketdata"]["data"],
            columns=data["marketdata"]["columns"],
        )

        if marketdata.empty or column not in marketdata.columns:
            if asset_type == "index":
                return np.nan
            bid = pd.to_numeric(marketdata["BID"], errors="coerce")
            ask = pd.to_numeric(marketdata["OFFER"], errors="coerce")
            spread = pd.to_numeric(marketdata["SPREAD"], errors="coerce")
            market_prices = (
                (bid + spread / 2)
                .combine_first(ask - spread / 2)
                .combine_first(bid)
                .combine_first(ask)
                .dropna()
            )
            if market_prices.empty:
                return np.nan
            return market_prices.iloc[0]

        market_prices = pd.Series(pd.to_numeric(marketdata[column], errors="coerce")).dropna()
        if market_prices.empty:
            return np.nan

        return market_prices.iloc[0]

    spot_prices = {
        stock_code: get_stock_market_price(stock_code)
        for stock_code in futData["count_with"].dropna().unique()
    }

    df = pd.DataFrame(
        list(spot_prices.items()),
        columns=["stock_code", "spot_price"]
    )

    futData = futData.merge(
        df,
        left_on="count_with",
        right_on="stock_code",
        how="left",
    )
    futData["t"] = futData["DaysToExp"]

    futData["is_announced"] = 0
    futData["most_common_day"] = np.nan
    futData["most_common_month"] = np.nan
    futData["second_most_common_day"] = np.nan
    futData["second_most_common_month"] = np.nan
    futData["div_size"] = np.nan
    futData["settlementprice_theory"] = np.nan
    futData["is_div_implied"] = 0
    futData["discounted_div_size"] = np.nan
    futData["t1_div_rates"] = np.nan
    futData["days_to_div"] = np.nan

    futData["F"] = get_future_price(futData)
    futData["SpotPrice"] = futData["spot_price"].copy()
    if asset_type == "stock":
        avg_dividends = get_avg_dividends().rename(columns={
            "Тикер": "stock_code",
            "средний_дивиденд": "avg_dividend",
            # "средний_дивиденд_индексированный": "avg_indexed_dividend",
            "самый_частый_месяц_дивиденда": "avg_most_common_month",
            "самый_частый_день_дивиденда": "avg_most_common_day",
            "второй_самый_частый_месяц_дивиденда": "avg_second_most_common_month",
            "второй_самый_частый_день_дивиденда": "avg_second_most_common_day",
        })

        futData = futData.merge(
            avg_dividends[[
                "stock_code",
                "avg_dividend",
                "avg_most_common_month",
                "avg_most_common_day",
                "avg_second_most_common_month",
                "avg_second_most_common_day",
            ]],
            left_on="count_with",
            right_on="stock_code",
            how="left",
        )
        futData["most_common_month"] = futData["avg_most_common_month"]
        futData["most_common_day"] = futData["avg_most_common_day"]
        futData["second_most_common_month"] = futData["avg_second_most_common_month"]
        futData["second_most_common_day"] = futData["avg_second_most_common_day"]

        if announced_dividends is None or announced_dividends.empty:
            announced = pd.DataFrame(columns=["stock_code", "announced_dividend_date", "announced_dividend"])
        else:
            announced = announced_dividends.copy()
            announced["stock_code"] = announced["Тикер"].astype("string").str.split(",").str[0].str.strip()
            announced["announced_dividend_date"] = (
                pd.to_datetime(announced["Экс-дивидендная дата"], format="%d.%m.%Y", errors="coerce")
                .combine_first(pd.to_datetime(announced["Закрытие реестра"], format="%d.%m.%Y", errors="coerce"))
            )
            announced["announced_dividend"] = pd.to_numeric(announced["Дивиденд"], errors="coerce")

            announced = announced[
                announced["stock_code"].notna()
                & announced["Валюта"].eq("RUB")
                & announced["announced_dividend_date"].notna()
                & (announced["announced_dividend_date"] > trade_date)
            ][["stock_code", "announced_dividend_date", "announced_dividend"]]

        announced_by_stock = {
            stock_code: group
            for stock_code, group in announced.groupby("stock_code", sort=False)
        }
        announced_flags = []
        announced_dividend_sizes = []
        announced_days_to_div = []
        for _, row in futData.iterrows():
            stock_dividends = announced_by_stock.get(row["count_with"])
            if stock_dividends is None or pd.isna(row["LASTTRADEDATE_DT"]):
                announced_flags.append(0)
                announced_dividend_sizes.append(np.nan)
                announced_days_to_div.append(np.nan)
                continue

            dividends_before_expiration = (
                stock_dividends.loc[
                    stock_dividends["announced_dividend_date"] <= row["LASTTRADEDATE_DT"]
                    ]
                .sort_values("announced_dividend_date")
            )

            if dividends_before_expiration.empty:
                announced_flags.append(0)
                announced_dividend_sizes.append(np.nan)
                announced_days_to_div.append(np.nan)
                continue

            nearest_dividend = dividends_before_expiration.iloc[0]

            announced_flags.append(1)
            announced_dividend_sizes.append(nearest_dividend["announced_dividend"])
            announced_days_to_div.append(
                (nearest_dividend["announced_dividend_date"] - trade_date).days
            )
        # 1. is_announced, div_size
        futData["is_announced"] = announced_flags
        futData["div_size"] = np.where(
            futData["is_announced"] == 1,
            announced_dividend_sizes,
            futData["avg_dividend"],
        )

        # 2. expected_div_date, days_to_div
        first_expected_div_date = pd.to_datetime(
            {
                "year": trade_date.year,
                "month": futData["most_common_month"],
                "day": futData["most_common_day"],
            },
            errors="coerce",
        )
        first_expected_div_date = first_expected_div_date.where(
            first_expected_div_date > trade_date,
            first_expected_div_date + pd.DateOffset(years=1),
        )
        first_expected_days_to_div = (first_expected_div_date - trade_date).dt.days

        second_expected_div_date = pd.to_datetime(
            {
                "year": trade_date.year,
                "month": futData["second_most_common_month"],
                "day": futData["second_most_common_day"],
            },
            errors="coerce",
        )
        second_expected_div_date = second_expected_div_date.where(
            second_expected_div_date > trade_date,
            second_expected_div_date + pd.DateOffset(years=1),
        )
        second_expected_days_to_div = (second_expected_div_date - trade_date).dt.days

        first_dividend_in_life = first_expected_days_to_div.notna() & (first_expected_days_to_div <= futData["t"])
        second_dividend_in_life = second_expected_days_to_div.notna() & (second_expected_days_to_div <= futData["t"])
        expected_days_to_div = np.select(
            [first_dividend_in_life, second_dividend_in_life],
            [first_expected_days_to_div, second_expected_days_to_div],
            default=np.nan,
        )

        futData["days_to_div"] = np.where(
            futData["is_announced"] == 1,
            announced_days_to_div,
            expected_days_to_div
        )

        # 3. t1_div_rates
        t1_div_rates = get_nearest_g_curve_rates(futData["days_to_div"])
        futData["t1_div_rates"] = t1_div_rates
        # 4. discounted_div_size
        futData["discounted_div_size"] = np.where(
            futData["days_to_div"].notna() & (futData["days_to_div"] <= futData["t"]),
            futData["div_size"] / np.exp(futData["t1_div_rates"] * futData["days_to_div"] / 365),
            np.nan,
        )
        # 5. settlementprice_theory
        t_theory_rates = get_nearest_g_curve_rates(futData["t"])
        theory_base = futData["spot_price"]
        futData["settlementprice_theory"] = np.where(
            (theory_base > 0) & (futData["t"] >= 0) & t_theory_rates.notna(),
            theory_base * np.exp(t_theory_rates * futData["t"] / 365) * futData["LOTVOLUME"] * futData["MINSTEP"] / futData["STEPPRICE"],
            np.nan,
        )

        # 6. is_div_implied
        non_perpetual_mask = ~futData["ASSETCODE"].isin(perpetual_futures)
        futData["is_div_implied"] = np.where(
            non_perpetual_mask
            & (
                (futData["is_announced"] == 1)
                | (
                        (futData["days_to_div"] <= futData["t"])
                        & (
                            (futData["settlementprice_theory"] / futData["SETTLEPRICE"] - 1)
                            >= 0.87 * futData["discounted_div_size"] / futData["SpotPrice"]
                        )
                )
            ),
            1,
            0,
        )

        futData = futData.drop(
            columns=[
                "stock_code_y",
                "avg_dividend",
                "avg_most_common_month",
                "avg_most_common_day",
                "avg_second_most_common_month",
                "avg_second_most_common_day",
            ],
            errors="ignore",
        )
    # 8. R
    div_adjusted_spot = futData["spot_price"] - futData["discounted_div_size"]
    futData["R"] = np.where(
        (futData["is_div_implied"] == 1)
        & (asset_type == "stock")
        & (futData["F"] > 0)
        & (div_adjusted_spot > 0)
        & (futData["t"] > 0),
        365 * np.log(futData["F"] / div_adjusted_spot) / futData["t"],
        np.where(
            (futData["F"] > 0) & (futData["SpotPrice"] > 0) & (futData["t"] > 0),
            365 * np.log(futData["F"] / futData["SpotPrice"]) / futData["t"],
            np.nan,
        )
    )

    return futData[[
        "TRADEDATE",
        "ASSETCODE",
        't',
        'R',
        "SETTLEPRICE",
        "underlying_asset",
        "SpotPrice",
        "is_announced",
        "most_common_day",
        "most_common_month",
        "second_most_common_day",
        "second_most_common_month",
        "div_size",
        "days_to_div",
        "discounted_div_size",
        "settlementprice_theory",
        "is_div_implied",
        "F",
        "t1_div_rates",
        "asset_type",
        "is_not_rub"
    ]]

### логика с проверкой отклонения ставки от руонии
def check_rate(futData):
    ruon = sdfi_ruonia()[["days", "ruonia_year"]]
    new_data = futData.merge(
        ruon,
        left_on="t",
        right_on="days",
        how="left"
    )
    mask = (
            new_data["ruonia_year"].notna()
            & new_data["R"].notna()
            & (new_data["asset_type"] == "stock")
            & (new_data["is_not_rub"] == 0)
            & (abs(new_data["R"] - new_data["ruonia_year"]) * 100 > 10)
    )

    new_data.loc[mask, "R"] = new_data.loc[mask, "ruonia_year"]

    return new_data

def MakeCalculations(futData, mapped, tradedate, announced_dividends=None):
    # Делаем преобразования и расчеты
    futData["TRADEDATE"] = tradedate
    futData["LASTTRADEDATE_DT"] = ConvertDates(futData["LASTTRADEDATE"])
    futData["DaysToExp"] = (futData["LASTTRADEDATE_DT"] - pd.to_datetime(tradedate)).dt.days
    for column in ["DaysToExp", "SETTLEPRICE", "STEPPRICE", "LOTVOLUME", "MINSTEP"]:
        futData[column] = pd.to_numeric(futData[column], errors="coerce")
    tmp = futData.merge(
        mapped,
        left_on='ASSETCODE',
        right_on='assetcode'
    ).reset_index(drop=True)
    if "perpetual_is_spot" not in tmp.columns:
        tmp["perpetual_is_spot"] = 0
    tmp["_row_id"] = tmp.index
    types = tmp["asset_type"].unique()
    res = []
    for type in types:
        mask = (tmp["asset_type"] == type)
        type_data = tmp[mask].copy().reset_index(drop=True)
        type_row_ids = type_data["_row_id"].copy()
        perpetual_spot_mask = pd.to_numeric(type_data["perpetual_is_spot"], errors="coerce").fillna(0) == 1
        pre_res_parts = []

        if perpetual_spot_mask.any():
            pre_res_parts.append(perpetual_future_is_spot(
                type_data.loc[perpetual_spot_mask].copy().reset_index(drop=True)
            ))

        type_data = type_data.loc[~perpetual_spot_mask].copy().reset_index(drop=True)
        if type_data.empty:
            pre_res = pd.concat(pre_res_parts, ignore_index=True)
            res.append(pre_res)
            tmp = tmp[~tmp["_row_id"].isin(type_row_ids)]
            continue

        if type in ["stock", "index"]:
            forced_future_mask = type_data["ASSETCODE"].isin(force_future_is_spot_assets)

            if (~forced_future_mask).any():
                asset_spot_data = type_data.loc[~forced_future_mask].copy().reset_index(drop=True)
                pre_res = asset_is_spot(asset_spot_data, tradedate, type, announced_dividends)
                bad_mask = pre_res["R"].isna() & (pre_res["t"] != 0)
                fallback = future_is_spot(asset_spot_data.loc[bad_mask].copy())
                pre_res_parts.append(pd.concat(
                    [pre_res.loc[~bad_mask], fallback],
                    ignore_index=True
                ))

            if forced_future_mask.any():
                pre_res_parts.append(future_is_spot(type_data.loc[forced_future_mask].copy()))

            pre_res = pd.concat(pre_res_parts, ignore_index=True)
        else:
            pre_res = future_is_spot(type_data)
            if pre_res_parts:
                pre_res_parts.append(pre_res)
                pre_res = pd.concat(pre_res_parts, ignore_index=True)
        res.append(pre_res)
        tmp = tmp[~tmp["_row_id"].isin(type_row_ids)]
    df = pd.DataFrame(pd.concat(res, ignore_index=True))
    df_final = check_rate(df)
    return df_final[[
        "TRADEDATE",
        "ASSETCODE",
        't',
        'R',
        "SETTLEPRICE",
        "underlying_asset",
        "SpotPrice",
        "is_announced",
        "most_common_day",
        "most_common_month",
        "second_most_common_day",
        "second_most_common_month",
        "div_size",
        "days_to_div",
        "discounted_div_size",
        "settlementprice_theory",
        "is_div_implied",
        "F",
        "t1_div_rates",
        "asset_type",
        "is_not_rub"
    ]]
