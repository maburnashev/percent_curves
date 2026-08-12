import glob
import argparse
import os
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


def _prepare_download_folder(download_folder):
    """Готовит папку для загрузок с Cbonds."""
    if not os.path.exists(download_folder):
        os.makedirs(download_folder)
    for old_file in glob.glob(os.path.join(download_folder, "*.xlsx")):
        try:
            os.remove(old_file)
        except OSError:
            pass


def _build_chrome(download_folder, headless=False, profile_dir=None):
    """Создает настроенный экземпляр Chrome."""
    chrome_options = Options()
    if headless:
        chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-first-run")
    chrome_options.add_argument("--no-default-browser-check")
    if profile_dir:
        chrome_options.add_argument(f"--user-data-dir={profile_dir}")
    prefs = {
        "download.default_directory": download_folder,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    }
    chrome_options.add_experimental_option("prefs", prefs)
    driver = webdriver.Chrome(options=chrome_options)
    driver.execute_cdp_cmd(
        "Page.setDownloadBehavior",
        {"behavior": "allow", "downloadPath": os.path.abspath(download_folder)},
    )
    return driver


def _close_cookie_panel(driver):
    """Закрывает панель cookie на сайте."""
    cookie_selectors = [
        "//button[contains(text(), 'Принять')]",
        "//button[contains(text(), 'OK')]",
        "//button[contains(text(), 'Согласен')]",
        "//a[contains(text(), 'Принять')]",
        "//div[contains(@class, 'cookie')]//button",
        "//button[contains(@class, 'cookie')]",
    ]
    for selector in cookie_selectors:
        try:
            cookie_btn = driver.find_element(By.XPATH, selector)
            if cookie_btn.is_displayed():
                cookie_btn.click()
                time.sleep(3)
                return True
        except Exception:
            continue
    return False


def _login_to_cbonds(driver, wait, login, password):
    """Авторизуется на сайте Cbonds."""
    driver.get("https://cbonds.ru/login/")
    time.sleep(2)
    login_input = wait.until(
        EC.visibility_of_element_located(
            (
                By.XPATH,
                "//input[@type='email'] | //input[@type='text'] | //input[@name='login'] | "
                "//input[@name='email'] | //input[contains(@placeholder, 'Email')] | "
                "//input[contains(@placeholder, 'Логин')]",
            )
        )
    )
    login_input.clear()
    login_input.send_keys(login)

    password_input = wait.until(
        EC.visibility_of_element_located((By.XPATH, "//input[@type='password']"))
    )
    password_input.clear()
    password_input.send_keys(password)

    submit_btn = wait.until(
        EC.element_to_be_clickable(
            (
                By.XPATH,
                "//button[@type='submit'] | //button[contains(text(), 'Войти')] | //input[@type='submit']",
            )
        )
    )
    submit_btn.click()
    wait.until(
        lambda d: "login" not in d.current_url.lower()
        or not any(
            field.is_displayed()
            for field in d.find_elements(By.XPATH, "//input[@type='password']")
        )
    )
    _close_cookie_panel(driver)


def _format_cbonds_date(value):
    """Приводит дату к формату YYYY-MM-DD, который нужен фильтрам Cbonds."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")

    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")

    value = str(value).strip()
    for date_format in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, date_format).strftime("%Y-%m-%d")
        except ValueError:
            continue
    try:
        return pd.to_datetime(value).strftime("%Y-%m-%d")
    except ValueError:
        raise ValueError("Дата должна быть в формате YYYY-MM-DD или DD.MM.YYYY.")


def _build_dividends_calendar_url(tradedate, max_date="2030-12-31", trading_ground_id="0-2"):
    """Собирает ссылку на дивидендный календарь с нужной начальной датой."""
    params = {
        "trading_ground_id": trading_ground_id,
        "date_of_ex_dividendMax": _format_cbonds_date(max_date),
        "date_of_ex_dividendMin": _format_cbonds_date(tradedate),
    }
    return "https://cbonds.ru/dividends-calendar/?" + urlencode(params)


def _wait_for_downloaded_excel(download_folder, old_files, timeout=60):
    """Ждет новый Excel-файл и возвращает путь к нему."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        temp_files = glob.glob(os.path.join(download_folder, "*.crdownload"))
        files = glob.glob(os.path.join(download_folder, "*.xlsx"))
        files = [
            path
            for path in files
            if path not in old_files and not path.endswith(".crdownload")
        ]
        if files and not temp_files:
            file_path = max(files, key=os.path.getctime)
            time.sleep(2)
            return file_path
        time.sleep(1)
    return None


def _extract_visible_table(driver):
    """Читает видимую таблицу со страницы, если Excel-файл не скачался."""
    tables = driver.find_elements(By.TAG_NAME, "table")
    best_rows = []
    best_headers = []

    for table in tables:
        rows = table.find_elements(By.XPATH, ".//tr")
        parsed_rows = []
        headers = [cell.text.strip() for cell in table.find_elements(By.XPATH, ".//thead//th")]

        for row in rows:
            cells = row.find_elements(By.XPATH, ".//th|.//td")
            values = [cell.text.strip() for cell in cells]
            if any(values):
                parsed_rows.append(values)

        if len(parsed_rows) > len(best_rows):
            best_rows = parsed_rows
            best_headers = headers

    if not best_rows:
        return pd.DataFrame()

    if best_headers and len(best_headers) == len(best_rows[0]):
        data_rows = best_rows[1:] if best_rows[0] == best_headers else best_rows
        return pd.DataFrame(data_rows, columns=best_headers)

    first_row = best_rows[0]
    data_rows = best_rows[1:]
    if data_rows and all(first_row) and len(first_row) == len(data_rows[0]):
        return pd.DataFrame(data_rows, columns=first_row)

    return pd.DataFrame(best_rows)


def _download_dividends_calendar_excel(driver, wait, download_folder, tradedate):
    """Открывает календарь дивидендов и скачивает таблицу в Excel."""
    url = _build_dividends_calendar_url(tradedate)
    driver.get(url)
    time.sleep(3)
    _close_cookie_panel(driver)

    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))
    old_files = set(glob.glob(os.path.join(download_folder, "*.xlsx")))

    excel_btn = wait.until(
        EC.element_to_be_clickable(
            (
                By.XPATH,
                "//*[self::button or self::a or self::input]"
                "[contains(normalize-space(.), 'Скачать в Excel') "
                "or @value='Скачать в Excel' "
                "or contains(@title, 'Excel') "
                "or contains(@href, 'excel')]",
            )
        )
    )
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", excel_btn)
    time.sleep(1)
    try:
        excel_btn.click()
    except Exception:
        driver.execute_script("arguments[0].click();", excel_btn)

    return _wait_for_downloaded_excel(download_folder, old_files)


def _normalize_columns(df):
    """Убирает переносы строк и лишние пробелы в названиях колонок."""
    df = df.copy()
    df.columns = [
        " ".join(str(column).replace("\n", " ").split())
        for column in df.columns
    ]
    return df


def _required_dividend_columns():
    """Возвращает список полей, которые должны быть в таблице дивидендов."""
    return [
        "Название",
        "Биржа",
        "Тикер",
        "Отрасль",
        "Дивиденд",
        "Дивидендная доходность, %",
        "Последняя дата приобретения",
        "Экс-дивидендная дата",
        "Закрытие реестра",
        "Дата выплаты",
    ]


def _validate_dividend_columns(df):
    """Проверяет, что в таблице есть все поля с дивидендного календаря."""
    missing_columns = [
        column
        for column in _required_dividend_columns()
        if column not in df.columns
    ]
    if missing_columns:
        raise ValueError(
            "В таблице Cbonds не найдены нужные поля: "
            + ", ".join(missing_columns)
            + ". Доступные поля: "
            + ", ".join(map(str, df.columns))
        )


def download_cbonds_dividends(
    tradedate,
    cbonds_login,
    cbonds_password,
    download_folder=None,
    headless=False,
    profile_dir=None,
):
    """Возвращает дивидендный календарь Cbonds отдельным DataFrame."""
    if download_folder is None:
        download_folder = os.path.join(os.getcwd(), "cbonds_temp_download")

    _prepare_download_folder(download_folder)
    driver = _build_chrome(download_folder, headless=headless, profile_dir=profile_dir)
    wait = WebDriverWait(driver, 20)

    try:
        _login_to_cbonds(driver, wait, cbonds_login, cbonds_password)
        file_path = _download_dividends_calendar_excel(driver, wait, download_folder, tradedate)

        if file_path is not None:
            df_dividends = pd.read_excel(file_path)
            try:
                os.remove(file_path)
            except OSError:
                pass
        else:
            # Запасной вариант нужен, если Cbonds поменяет кнопку выгрузки.
            df_dividends = _extract_visible_table(driver)

        df_dividends = _normalize_columns(df_dividends)
        if df_dividends.empty:
            raise ValueError("Не удалось получить таблицу дивидендного календаря Cbonds.")
        _validate_dividend_columns(df_dividends)

        return df_dividends
    finally:
        driver.quit()


def build_cbonds_dividends(
    report_date,
    tradedate,
    cbonds_login,
    cbonds_password,
    download_folder=None,
    headless=False,
    profile_dir=None,
):
    """Сохраняет дивидендный календарь Cbonds в отдельный DataFrame и Excel-файл."""
    if download_folder is None:
        download_folder = os.path.join(os.getcwd(), "cbonds_temp_download")

    df_dividends = download_cbonds_dividends(
        tradedate,
        cbonds_login,
        cbonds_password,
        download_folder=download_folder,
        headless=headless,
        profile_dir=profile_dir,
    )

    output_folder = Path(__file__).resolve().parent / f"../data_{report_date}"
    output_folder.mkdir(exist_ok=True)
    output_path = output_folder / f"df_dividends_announced.xlsx"
    df_dividends.to_excel(output_path, index=False)
    print(f"Сохранено строк: {len(df_dividends)}")
    print(f"Файл: {output_path}")
    return {"df_dividends": df_dividends}


def _parse_args():
    """Читает параметры для самостоятельного запуска скрипта."""
    parser = argparse.ArgumentParser(description="Скачать дивидендный календарь Cbonds в Excel.")
    parser.add_argument(
        "--tradedate",
        default=datetime.today().strftime("%Y-%m-%d"),
        help="Минимальная экс-дивидендная дата: YYYY-MM-DD или DD.MM.YYYY.",
    )
    parser.add_argument(
        "--login",
        default=None,
        help="Логин Cbonds. Если не задан, берется из .env.",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="Пароль Cbonds. Если не задан, берется из .env.",
    )
    parser.add_argument(
        "--env-file",
        default=str(Path(__file__).resolve().parent / "../.env"),
        help="Путь к .env файлу с CBONDS_LOGIN и CBONDS_PASSWORD.",
    )
    parser.add_argument(
        "--download-folder",
        default=str(Path(__file__).resolve().parent / "cbonds_temp_download"),
        help="Папка для временной Excel-выгрузки.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Запустить Chrome без видимого окна.",
    )
    parser.add_argument(
        "--profile-dir",
        default=None,
        help="Папка профиля Chrome для сохранения cookies и сессии входа.",
    )
    return parser.parse_args()


def _resolve_cbonds_credentials(login_arg, password_arg, env_file):
    """Берет логин и пароль из аргументов или .env."""
    load_dotenv(env_file)
    cbonds_login = login_arg or os.getenv("CBONDS_LOGIN")
    cbonds_password = password_arg or os.getenv("CBONDS_PASSWORD")
    return cbonds_login, cbonds_password


def build():
    """Запускает скачивание дивидендов с параметрами из командной строки."""
    args = _parse_args()
    cbonds_login, cbonds_password = _resolve_cbonds_credentials(
        args.login,
        args.password,
        args.env_file,
    )

    if not cbonds_login or not cbonds_password:
        raise ValueError(
            "Не найден логин или пароль Cbonds. Добавьте CBONDS_LOGIN и CBONDS_PASSWORD в .env "
            "или передайте их через --login/--password."
        )

    report_date = _format_cbonds_date(args.tradedate)
    build_cbonds_dividends(
        report_date=report_date,
        tradedate=args.tradedate,
        cbonds_login=cbonds_login,
        cbonds_password=cbonds_password,
        download_folder=args.download_folder,
        headless=args.headless,
        profile_dir=args.profile_dir,
    )
    os.removedirs("src/cbonds_temp_download")
