import json
import os
import re
import time
from datetime import datetime, timezone, timedelta

import requests


CONFIG_FILE = "config/funds.json"
OUTPUT_DIR = "funds"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "Referer": "https://fund.eastmoney.com/",
    "Accept": "*/*",
}

BEIJING_TZ = timezone(timedelta(hours=8))


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    funds = config.get("funds", [])

    if not funds:
        raise RuntimeError("No funds found in config/funds.json")

    return funds


def get_fund_data(code, configured_name):
    url = (
        f"https://fund.eastmoney.com/"
        f"pingzhongdata/{code}.js"
    )

    print("=" * 80)
    print(f"Fetching {code}...")

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    text = response.text

    print(f"HTTP status: {response.status_code}")
    print(f"Response length: {len(text)}")

    # ------------------------------------------------------------------
    # Fund name
    # ------------------------------------------------------------------

    name_match = re.search(
        r'var\s+fS_name\s*=\s*"([^"]*)"',
        text,
    )

    fund_name = (
        name_match.group(1)
        if name_match
        else configured_name
    )

    # ------------------------------------------------------------------
    # Data_netWorthTrend
    # ------------------------------------------------------------------

    match = re.search(
        r'var\s+Data_netWorthTrend\s*=\s*(.*?);',
        text,
        re.S,
    )

    if not match:
        raise RuntimeError(
            f"{code}: Cannot find Data_netWorthTrend"
        )

    raw_text = match.group(1).strip()

    try:
        raw_data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        print("Failed to parse Data_netWorthTrend")
        print(raw_text[:500])
        raise RuntimeError(
            f"{code}: Invalid Data_netWorthTrend JSON: {e}"
        )

    print(f"Raw NAV records: {len(raw_data)}")

    result = []

    # ------------------------------------------------------------------
    # Parse NAV records
    # ------------------------------------------------------------------

    for item in raw_data:

        if not isinstance(item, dict):
            continue

        timestamp = item.get("x")
        nav = item.get("y")

        if timestamp is None or nav is None:
            continue

        try:
            timestamp = float(timestamp)
            nav = float(nav)
        except (ValueError, TypeError):
            continue

        dt = datetime.fromtimestamp(
            timestamp / 1000,
            tz=timezone.utc,
        ).astimezone(BEIJING_TZ)

        date = dt.strftime("%Y-%m-%d")

        result.append(
            {
                "date": date,
                "close": nav,
            }
        )

    if not result:
        raise RuntimeError(
            f"{code}: No valid NAV records found"
        )

    # Remove duplicate dates
    unique = {}

    for item in result:
        unique[item["date"]] = item["close"]

    result = [
        {
            "date": date,
            "close": close,
        }
        for date, close in unique.items()
    ]

    # Newest first
    result.sort(
        key=lambda x: x["date"],
        reverse=True,
    )

    return fund_name, result


def save_fund(code, fund_name, data):

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True,
    )

    output_file = os.path.join(
        OUTPUT_DIR,
        f"{code}.json",
    )

    updated = datetime.now(
        BEIJING_TZ
    ).isoformat()

    output = {
        "symbol": code,
        "name": fund_name,
        "currency": "CNY",
        "updated": updated,
        "data": data,
    }

    with open(
        output_file,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            output,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(
        f"Saved {len(data)} records → "
        f"{output_file}"
    )

    print("Latest NAV:")

    for item in data[:3]:
        print(
            f"  {item['date']} "
            f"{item['close']:.4f}"
        )


def main():

    funds = load_config()

    print(
        f"Found {len(funds)} funds in configuration."
    )

    success = 0
    failed = 0

    for fund in funds:

        code = str(fund["code"]).strip()
        name = fund.get("name", "")

        if not fund.get("enabled", True):
            print(f"Skipping disabled fund: {code}")
            continue

        try:

            fund_name, data = get_fund_data(
                code,
                name,
            )

            save_fund(
                code,
                fund_name,
                data,
            )

            success += 1

        except Exception as e:

            failed += 1

            print(
                f"ERROR: {code}: {e}"
            )

        # Avoid requesting too quickly
        time.sleep(2)

    print("=" * 80)

    print(
        f"Finished. "
        f"Success: {success}, "
        f"Failed: {failed}"
    )

    if failed > 0:
        raise RuntimeError(
            f"{failed} fund(s) failed."
        )


if __name__ == "__main__":
    main()
