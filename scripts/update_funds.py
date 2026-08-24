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


def now_beijing():
    return datetime.now(BEIJING_TZ)


def now_iso():
    return now_beijing().isoformat()


def load_config():

    with open(
        CONFIG_FILE,
        "r",
        encoding="utf-8",
    ) as f:
        config = json.load(f)

    funds = config.get("funds", [])

    if not funds:
        raise RuntimeError(
            "No funds found in config/funds.json"
        )

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

    print(
        f"HTTP status: {response.status_code}"
    )

    print(
        f"Response length: {len(text)}"
    )

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

        raw_data = json.loads(
            raw_text
        )

    except json.JSONDecodeError as e:

        raise RuntimeError(
            f"Invalid Data_netWorthTrend JSON: {e}"
        )

    print(
        f"Raw NAV records: {len(raw_data)}"
    )

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

        except (
            ValueError,
            TypeError,
        ):

            continue

        # NAV 必须大于 0
        if nav <= 0:
            continue

        try:

            dt = datetime.fromtimestamp(
                timestamp / 1000,
                tz=timezone.utc,
            ).astimezone(
                BEIJING_TZ
            )

        except (
            ValueError,
            OverflowError,
        ):

            continue

        date = dt.strftime(
            "%Y-%m-%d"
        )

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

        unique[item["date"]] = item[
            "close"
        ]

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


def is_weekend(date_obj):

    return date_obj.weekday() >= 5


def business_days_since(date_str):

    try:

        latest_date = datetime.strptime(
            date_str,
            "%Y-%m-%d",
        ).date()

    except ValueError:

        return None

    today = now_beijing().date()

    if latest_date > today:

        return None

    count = 0

    current = latest_date

    while current < today:

        current += timedelta(days=1)

        if not is_weekend(
            current
        ):
            count += 1

    return count


def check_freshness(latest_date):

    business_days = (
        business_days_since(
            latest_date
        )
    )

    if business_days is None:

        return {
            "status": "error",
            "daysSinceUpdate": None,
            "message": "Invalid NAV date",
        }

    # ------------------------------------------------------------
    # 判断规则
    #
    # 0-2 个工作日：正常
    # 3-4 个工作日：可能延迟
    # >=5 个工作日：stale
    #
    # 这样可以避免周末、节假日造成误报。
    # ------------------------------------------------------------

    if business_days <= 2:

        return {
            "status": "ok",
            "daysSinceUpdate": business_days,
            "message": "NAV is fresh",
        }

    if business_days <= 4:

        return {
            "status": "warning",
            "daysSinceUpdate": business_days,
            "message": "NAV may be delayed",
        }

    return {
        "status": "stale",
        "daysSinceUpdate": business_days,
        "message": "NAV has not been updated recently",
    }


def save_fund(
    code,
    fund_name,
    data,
):

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True,
    )

    output_file = os.path.join(
        OUTPUT_DIR,
        f"{code}.json",
    )

    old_output = None

    # ------------------------------------------------------------
    # 读取旧数据
    # ------------------------------------------------------------

    if os.path.exists(
        output_file
    ):

        try:

            with open(
                output_file,
                "r",
                encoding="utf-8",
            ) as f:

                old_output = json.load(f)

        except Exception:

            print(
                f"Warning: cannot read existing "
                f"{output_file}"
            )

    old_data = (
        old_output.get(
            "data",
            [],
        )
        if old_output
        else []
    )

    old_latest = (
        old_data[0]
        if old_data
        else None
    )

    new_latest = (
        data[0]
        if data
        else None
    )

    # ------------------------------------------------------------
    # 判断是否真正产生了新数据
    # ------------------------------------------------------------

    data_changed = (
        old_latest != new_latest
        or len(old_data) != len(data)
    )

    if (
        old_output is not None
        and not data_changed
    ):

        print(
            f"No NAV change: {code}"
        )

        return False

    # ------------------------------------------------------------
    # 创建新 JSON
    # ------------------------------------------------------------

    output = {
        "symbol": code,
        "name": fund_name,
        "currency": "CNY",
        "updated": now_iso(),
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
            "name": configured_name,
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

        freshness = check_freshness(
            latest["date"]
        )

        # --------------------------------------------------------
        # 如果数据本身正常，但 freshness 有问题
        # --------------------------------------------------------

        if freshness["status"] != "ok":

            print(
                f"WARNING {code}: "
                f"{freshness['message']}"
            )

        return {
            "code": code,
            "name": fund_name,
            "status": freshness[
                "status"
            ],
            "latestDate": latest[
                "date"
            ],
            "latestNAV": latest[
                "close"
            ],
            "records": len(data),
            "daysSinceUpdate": freshness[
                "daysSinceUpdate"
            ],
            "changed": changed,
            "message": freshness[
                "message"
            ],
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
        f"Found {len(funds)} "
        f"funds in configuration."
    )

    results = []

    for fund in funds:

        result = process_fund(
            fund
        )

        results.append(
            result
        )

        # 请求间隔
        time.sleep(2)

    save_status(
        results
    )

    # ------------------------------------------------------------
    # 汇总
    # ------------------------------------------------------------

    success = sum(
        1
        for r in results
        if r["status"] == "ok"
    )

    warning = sum(
        1
        for r in results
        if r["status"] == "warning"
    )

    stale = sum(
        1
        for r in results
        if r["status"] == "stale"
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
        f"Warning: {warning}, "
        f"Stale: {stale}, "
        f"Failed: {failed}, "
        f"Disabled: {disabled}"
    )

    print(
        "Individual fund failures "
        "will not stop the workflow."
    )


if __name__ == "__main__":
    main()
