import json
import os
from datetime import datetime

import requests


FUND_CODE = "007194"
OUTPUT_FILE = "funds/007194.json"

URL = "https://api.fund.eastmoney.com/f10/lsjz"

PARAMS = {
    "fundCode": FUND_CODE,
    "pageIndex": 1,
    "pageSize": 10000,
    "startDate": "",
    "endDate": "",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "Referer": "https://fund.eastmoney.com/",
    "Accept": "application/json, text/plain, */*",
}


def get_nav_history():
    response = requests.get(
        URL,
        params=PARAMS,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    if not data.get("Data"):
        raise RuntimeError(f"API returned no Data: {data}")

    records = data["Data"].get("LSJZList", [])

    if not records:
        raise RuntimeError("API returned an empty LSJZList")

    result = []

    for item in records:
        date = item.get("FSRQ")
        nav = item.get("DWJZ")

        if not date or not nav:
            continue

        try:
            close = float(nav)
        except ValueError:
            continue

        result.append(
            {
                "date": date,
                "close": close,
            }
        )

    if not result:
        raise RuntimeError("No valid NAV records found")

    result.sort(key=lambda x: x["date"], reverse=True)

    return result


def save_json(data):
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    output = {
        "symbol": FUND_CODE,
        "name": "长城短债A",
        "currency": "CNY",
        "updated": datetime.now().astimezone().isoformat(),
        "data": data,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(
        f"Saved {len(data)} NAV records to {OUTPUT_FILE}"
    )

    print("Latest records:")

    for item in data[:5]:
        print(
            f"  {item['date']}  {item['close']:.4f}"
        )


if __name__ == "__main__":
    nav_history = get_nav_history()
    save_json(nav_history)
