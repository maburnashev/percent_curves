import pandas as pd
import requests
import xml.etree.ElementTree as ET
from urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)


def GetFutQuotes(date, meta="marketdata"):
    baseURL = "https://iss.moex.com/iss/engines/futures/markets/forts/securities"
    params = {
        "iss.meta": "off",
        "iss.only": meta,
        "date": date
    }

    response = requests.get(baseURL, params=params, verify=False)
    response.raise_for_status()

    root = ET.fromstring(response.text)

    data_rows = root.findall(".//row")
    rows = []
    for row in data_rows:
        rows.append(row.attrib)

    df = pd.DataFrame(rows)

    return df

def GetFutData(date):
    # Получаем исходные данные из ИСС
    df1 = GetFutQuotes(date)
    df1.to_csv(f'data_{date}/quotes_{date}.csv', index=False)
    df2 = GetFutQuotes(date, meta="securities")
    df2.to_csv(f'data_{date}/description_{date}.csv', index=False)

    # чтобы считать по РЦ предыдущего - раскомментировать закомментированное
    # и закомментировать строки 39-40 (следующие 2)
    futQuotesColumns = ["SECID", "SETTLEPRICE"]
    futParamsColumns = ["SECID", "SHORTNAME", "ASSETCODE", "LASTTRADEDATE", "LOTVOLUME", "STEPPRICE", "MINSTEP"]
    # futQuotesColumns = ["SECID"]
    # futParamsColumns = ["SECID", "SHORTNAME", "ASSETCODE", "LASTSETTLEPRICE", "LASTTRADEDATE", "LOTVOLUME", "STEPPRICE", "MINSTEP"]

    futQuotes = df1.reindex(columns=futQuotesColumns)
    futParams = df2.reindex(columns=futParamsColumns)

    futData = pd.merge(left=futParams, right=futQuotes, on="SECID", how="left")
    # futData["SETTLEPRICE"] = futData["LASTSETTLEPRICE"]
    return futData