import json
import os
import re
import time
from datetime import datetime, timezone, timedelta

import requests


CONFIG_FILE = "config/funds.json"
OUTPUT_DIR = "funds"
STATUS_FILE = "status.json"

BASE_URL = "https://fund.eastmoney.com/pingzhongdata/{}.js"

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


def now_iso():
    return datetime.now(BEIJING_TZ).isoformat()


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    funds = config.get("funds", [])

    if not funds:
        raise RuntimeError("No funds found in config/funds.json")

    return funds


def get_fund_data(code, configured_name):

    url = BASE_URL.format(code)

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

    # ------------------------------------------------------------
    # 基金名称
    # ------------------------------------------------------------

    name_match = re.search(
        r'var\s+fS_name\s*=\s*"([^"]*)"',
        text,
    )

    fund_name = (
        name_match.group(1)
        if name_match
        else configured_name
    )

    # ------------------------------------------------------------
    # Data_netWorthTrend
    # ------------------------------------------------------------

    match = re.search(
        r'var\s+Data_netWorthTrend\s*=\s*(.*?);',
        text,
        re.S,
    )

    if not match:
        raise RuntimeError(
            "Cannot find Data_netWorthTrend"
        )

    raw_text = match.group(1).strip()

    try:
        raw_data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Invalid Data_netWorthTrend JSON: {e}"
        )

    print(f"Raw NAV records: {len(raw_data)}")

    result = []

    # ------------------------------------------------------------
    # 解析净值
    # ------------------------------------------------------------

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

        # 基本数据质量检查
        if nav <= 0:
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
            "No valid NAV records found"
        )

    # ------------------------------------------------------------
    # 去除重复日期
    # ------------------------------------------------------------

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

    # 最新日期在前
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

    updated = now_iso()

    output = {
        "symbol": code,
        "name": fund_name,
        "currency": "CNY",
        "updated": updated,
        "data": data,
    }

    # ------------------------------------------------------------
    # 只有内容发生变化时才写入
    # ------------------------------------------------------------

    old_content = None

    if os.path.exists(output_file):

        with open(
            output_file,
            "r",
            encoding="utf-8",
        ) as f:
            old_content = f.read()

    new_content = json.dumps(
        output,
        ensure_ascii=False,
        indent=2,
    )

    if old_content == new_content:

        print(
            f"No content change: {output_file}"
        )

        return False

    with open(
        output_file,
        "w",
        encoding="utf-8",
    ) as f:
        f.write(new_content)

    print(
        f"Updated {output_file}"
    )

    return True


def process_fund(fund):

    code = str(
        fund["code"]
    ).strip()

    configured_name = fund.get(
        "name",
        "",
    )

    enabled = fund.get(
        "enabled",
        True,
    )

    if not enabled:

        print(
            f"Skipping disabled fund: {code}"
        )

        return {
            "code": code,
            "status": "disabled",
        }

    try:

        fund_name, data = get_fund_data(
            code,
            configured_name,
        )

        changed = save_fund(
            code,
            fund_name,
            data,
        )

        latest = data[0]

        return {
            "code": code,
            "name": fund_name,
            "status": "ok",
            "latestDate": latest["date"],
            "latestNAV": latest["close"],
            "records": len(data),
            "changed": changed,
        }

    except Exception as e:

        print(
            f"ERROR {code}: {e}"
        )

        return {
            "code": code,
            "name": configured_name,
            "status": "error",
            "error": str(e),
        }


def save_status(results):

    status = {
        "updated": now_iso(),
        "funds": {},
    }

    for result in results:

        code = result["code"]

        status["funds"][code] = result

    with open(
        STATUS_FILE,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            status,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(
        f"Saved {STATUS_FILE}"
    )


def main():

    funds = load_config()

    print(
        f"Found {len(funds)} funds in configuration."
    )

    results = []

    for fund in funds:

        result = process_fund(
            fund
        )

        results.append(
            result
        )

        # 防止请求过于频繁
        time.sleep(2)

    save_status(results)

    # ------------------------------------------------------------
    # 汇总
    # ------------------------------------------------------------

    success = sum(
        1
        for r in results
        if r["status"] == "ok"
    )

    failed = sum(
        1
        for r in results
        if r["status"] == "error"
    )

    disabled = sum(
        1
        for r in results
        if r["status"] == "disabled"
    )

    print("=" * 80)

    print(
        f"Finished. "
        f"Success: {success}, "
        f"Failed: {failed}, "
        f"Disabled: {disabled}"
    )

    # ------------------------------------------------------------
    # 注意：
    # 即使某只基金失败，也不让整个 Workflow 失败
    # ------------------------------------------------------------

    print(
        "Workflow will continue even if "
        "individual funds fail."
    )


if __name__ == "__main__":
    main()
