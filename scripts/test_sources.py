import requests

urls = [
    "https://stock.finance.sina.com.cn/fundInfo/api/openapi.php/FundInfoService.getFundNav?symbol=007194",
    "https://fund.eastmoney.com/pingzhongdata/007194.js",
]

headers = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
}

for url in urls:
    print("=" * 80)
    print(url)

    try:
        r = requests.get(
            url,
            headers=headers,
            timeout=30,
        )

        print("HTTP:", r.status_code)
        print("Content-Type:", r.headers.get("content-type"))
        print("Length:", len(r.text))
        print("First 1000 chars:")
        print(r.text[:1000])

    except Exception as e:
        print("ERROR:", repr(e))
