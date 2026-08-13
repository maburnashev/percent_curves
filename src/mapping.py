import pandas as pd
import numpy as np
import requests
from io import StringIO
from urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

perpetual_futures = ['USDRUBF', 'EURRUBF', 'CNYRUBF', 'IMOEX', 'RGBIF', 'GLDRUBF', 'SLVRUBF', 'SBERF', 'GAZPF', 'USDRUB_TOM', 'EURRUB_TOM', 'CNYRUB_TOM', 'SP500F', 'QQQF']

headers = {"User-Agent": "Mozilla/5.0"}
group_to_type = {
    "Indices": "index",
    "Equities": "stock",
    "Interest Rates": "rate",
    "FXs": "currency",
    "Commodities": "commodity",

    "Index futures": "index",
    "Single stock futures": "stock",
    "FX futures": "currency",
    "Fixed income futures": "rate",
    "Commodity futures": "commodity",
}

def GetAssetType(date, mapped):
    mapped['STEPPRICE'] = pd.to_numeric(mapped['STEPPRICE'], errors="coerce")
    html = requests.get(
        "https://www.moex.com/s1085",
        headers=headers,
        timeout=30,
    ).text

    code_table = pd.read_html(StringIO(html))[5]

    asset_types_1 = (
        code_table[["Contract's Group", "Code  of the underlying asset"]]
        .dropna()
        .rename(columns={
            "Contract's Group": "group",
            "Code  of the underlying asset": "assetcode",
        })
    )

    asset_types_1["asset_type"] = asset_types_1["group"].map(group_to_type)

    asset_types_1 = (
        asset_types_1[["assetcode", "asset_type"]]
        .dropna()
        .drop_duplicates(subset=["assetcode"])
    )
    html = requests.get(
        "https://www.moex.com/en/derivatives/select.aspx",
        headers=headers,
        timeout=30,
    ).text

    select_table = pd.read_html(StringIO(html))[0]

    records = []
    current_type = None

    for _, row in select_table.iterrows():
        code = row.iloc[0]
        title = row.iloc[1]

        if pd.notna(code) and code in group_to_type and title == code:
            current_type = group_to_type[code]
            continue

        if current_type is not None and pd.notna(code):
            records.append({
                "assetcode": str(code).strip(),
                "asset_type": current_type,
            })

    asset_types_2 = pd.DataFrame(records).drop_duplicates(subset=["assetcode"])
    fallback_types = pd.DataFrame([
        {"assetcode": "USDRUBTOM", "asset_type": "currency"},
        {"assetcode": "EURRUBTOM", "asset_type": "currency"},
        {"assetcode": "CNYRUBTOM", "asset_type": "currency"},
        {"assetcode": "UINR", "asset_type": "currency"},
    ])

    asset_types = (
        pd.concat([asset_types_2, asset_types_1, fallback_types], ignore_index=True)
        .drop_duplicates(subset=["assetcode"], keep="first")
    )

    mapped["assetcode"] = mapped["assetcode"].astype("string").str.strip()
    asset_types["assetcode"] = asset_types["assetcode"].astype("string").str.strip()

    mapped = mapped.drop(columns=["asset_type"], errors="ignore").merge(
        asset_types,
        on="assetcode",
        how="left",
    )
    mapped["asset_type"] = np.where(
        mapped["assetcode"].isin(["SPYF", "NASD"]),
        "index",
        mapped["asset_type"]
    )
    mapped = mapped[['assetcode', 'underlying_asset', 'asset_type', 'STEPPRICE']]

    mapped['count_with'] = mapped['underlying_asset'].where(
        ~mapped['assetcode'].isin(perpetual_futures),
        mapped['assetcode'].str[:-1],
    ).fillna(mapped['assetcode'])

    perpetual_spot_map = {
        "IMOEX": "IMOEX",
        "MXI": "IMOEX",
        "MIX": "IMOEX",
        "RGBI": "RGBIF",
        "RGBIF": "RGBIF",
        "Si": "USDRUBTOM",
        "USDM": "USDRUBTOM",
        "USDRUBTOM": "USDRUBTOM",
        "Eu": "EURRUBTOM",
        "EURM": "EURRUBTOM",
        "EURRUBTOM": "EURRUBTOM",
        "CNY": "CNYRUBTOM",
        "CNYRUBTOM": "CNYRUBTOM",
        "SPYF": "SP500F",
        "SP500F": "SP500F",
        "NASD": "QQQF",
        "QQQF": "QQQF",
    }
    mapped["perpetual_is_spot"] = 0
    perpetual_spot_mask = mapped["assetcode"].isin(perpetual_spot_map)
    mapped.loc[perpetual_spot_mask, "count_with"] = mapped.loc[
        perpetual_spot_mask,
        "assetcode",
    ].map(perpetual_spot_map)
    mapped.loc[perpetual_spot_mask, "perpetual_is_spot"] = 1

    mapped["is_not_rub"] = np.where(
        (
            (~mapped["STEPPRICE"].isin([1., 10.]) & (mapped["asset_type"].isin(["stock", "index"]))
            & (~mapped["assetcode"].isin(perpetual_spot_map.keys())))
            | (mapped["assetcode"].isin(["SPYF", "SP500F", "NASD", "QQQF"]))),
        1,
        0
    )
    mapped = mapped[["assetcode", "underlying_asset", "asset_type", "count_with", "is_not_rub", "perpetual_is_spot"]]
    mapped.to_csv(f'data_{date}/mapped_{date}.csv', index=False)
    return mapped

def MapSecurities(futDataPreRaw, tradedate):
    url = 'https://iss.moex.com//iss/statistics/engines/futures/markets/forts/series.json'
    params = {
        "date": tradedate,
    }
    response = requests.get(url, params)
    response.raise_for_status()
    data = response.json()
    ba = pd.DataFrame(data['series']['data'], columns=data['series']['columns'])
    ba['short_asset_code'] = ba['secid'].astype(str).str[:2]
    ba.to_csv(f'data_{tradedate}/ba_{tradedate}.csv', index=False)

    df = futDataPreRaw.copy()
    if "assetcode" not in df.columns:
        df["assetcode"] = df["ASSETCODE"]

    grouped = df[["assetcode", "STEPPRICE"]].drop_duplicates(subset=["assetcode"])
    mapped = grouped.merge(
        ba[['asset_code', 'underlying_asset', 'short_asset_code']],
        left_on=['assetcode'],
        right_on=['asset_code'],
        how='outer'
    )
    mapped = mapped[['assetcode', 'underlying_asset', 'short_asset_code', 'STEPPRICE']].drop_duplicates(subset=["assetcode"])
    mapped["underlying_asset"] = (
        mapped["underlying_asset"]
        .replace(["", "None", None], pd.NA)
        .astype("string")
    )
    # получение доп информации по базовым активам
    html = requests.get(
        "https://www.moex.com/s1085",
        headers=headers,
        timeout=30,
    ).text

    code_table = pd.read_html(StringIO(html))[5]
    code_table.columns = (code_table.columns.astype(str).str.replace(r"\s+", " ", regex=True).str.replace('"', "",
                                                                                                          regex=False).str.strip())

    underlying_assets = (
        code_table[["Futures and Options codes(field C)", "Code of the underlying asset"]]
        .dropna()
        .rename(columns={
            "Futures and Options codes(field C)": "short_asset_code",
            "Code of the underlying asset": "underlying_asset_code_new",
        })
    )
    mapped = mapped.merge(
        underlying_assets,
        on='short_asset_code',
        how='left'
    )
    mapped["underlying_asset"] = mapped["underlying_asset"].fillna(
        mapped["underlying_asset_code_new"]
    )
    mapped = mapped[['assetcode', 'short_asset_code', 'underlying_asset', 'STEPPRICE']]
    return GetAssetType(tradedate, mapped)
