import json
import os
import re
from datetime import datetime, timezone, timedelta

import requests


FUND_CODE = "007194"
OUTPUT_FILE = "funds/007194.json"

URL = f"https://fund.eastmoney.com/pingzhongdata/{FUND_CODE}.js"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "Referer": "https://fund.eastmoney.com/",
    "Accept": "*/*",
}


def get_fund_data():
    response = requests.get(
        URL,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    text = response.text

    print(f"HTTP status: {response.status_code}")
    print(f"Response length: {len(text)}")

    # 基金名称
    name_match = re.search(
        r'var\s+fS_name\s*=\s*"([^"]*)"',
        text
    )

    fund_name = (
        name_match.group(1)
        if name_match
        else f"基金 {FUND_CODE}"
    )

    # 提取 Data_netWorthTrend
    match = re.search(
        r'var\s+Data_netWorthTrend\s*=\s*(\[\[.*?\]\]);',
        text,
        re.S,
    )

    if not match:
        raise RuntimeError(
            "Cannot find Data_netWorthTrend in response"
        )

    raw_data = json.loads(match.group(1))

    print(f"Raw NAV records: {len(raw_data)}")

    result = []

    # Data_netWorthTrend 的结构通常为：
    # [timestamp, unit NAV, accumulated NAV, ...]
    for item in raw_data:
        if not isinstance(item, list) or len(item) < 2:
            continue

        timestamp = item[0]
        nav = item[1]

        try:
            timestamp = float(timestamp)
            nav = float(nav)
        except (ValueError, TypeError):
            continue

        # JavaScript timestamp 是毫秒
        dt = datetime.fromtimestamp(
            timestamp / 1000,
            tz=timezone.utc,
        )

        # 转成北京时间
        beijing_tz = timezone(timedelta(hours=8))
        dt = dt.astimezone(beijing_tz)

        date = dt.strftime("%Y-%m-%d")

        result.append(
            {
                "date": date,
                "close": nav,
            }
        )

    if not result:
        raise RuntimeError("No valid NAV records found")

    # 日期从新到旧
    result.sort(
        key=lambda x: x["date"],
        reverse=True,
    )

    return fund_name, result


def save_json(fund_name, data):
    os.makedirs(
        os.path.dirname(OUTPUT_FILE),
        exist_ok=True,
    )

    now = datetime.now(
        timezone(timedelta(hours=8))
    ).isoformat()

    output = {
        "symbol": FUND_CODE,
        "name": fund_name,
        "currency": "CNY",
        "updated": now,
        "data": data,
    }

    with open(
        OUTPUT_FILE,
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
        f"Saved {len(data)} NAV records "
        f"to {OUTPUT_FILE}"
    )

    print("\nLatest 10 NAV records:")

    for item in data[:10]:
        print(
            f"  {item['date']}  "
            f"{item['close']:.4f}"
        )


if __name__ == "__main__":
    fund_name, nav_history = get_fund_data()
    save_json(fund_name, nav_history)
