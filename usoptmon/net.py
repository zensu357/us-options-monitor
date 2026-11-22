"""HTTP 抓取辅助:统一的浏览器头 / 重试 / 超时。

CBOE delayed quotes 需要"看起来像浏览器"的完整 Sec-Fetch 头,否则被
Cloudflare 403;Yahoo chart API 只需普通 UA。
"""

import time

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

CBOE_HEADERS = {
    "User-Agent": UA,
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.cboe.com/",
    "Origin": "https://www.cboe.com",
    "Sec-Fetch-Dest": "script",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

YAHOO_HEADERS = {"User-Agent": UA}

RETRIES = 3
TIMEOUT = 30

# Cloudflare bot management:首个请求通过后下发 __cf_bm cookie,
# 后续请求必须回带,否则 403 —— 因此全程复用同一 Session。
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA})


def get_json(url, headers=None, retries=RETRIES, timeout=TIMEOUT):
    last = None
    for i in range(retries):
        try:
            r = SESSION.get(url, headers=headers or YAHOO_HEADERS,
                            timeout=timeout)
            if r.status_code == 200:
                return r.json()
            last = RuntimeError(f"HTTP {r.status_code} for {url}")
        except Exception as e:  # noqa: BLE001 - 网络失败统一重试
            last = e
        time.sleep(1.5 * (i + 1))
    raise last


def get_bytes(url, headers=None, retries=RETRIES, timeout=TIMEOUT):
    last = None
    for i in range(retries):
        try:
            r = SESSION.get(url, headers=headers or YAHOO_HEADERS,
                            timeout=timeout)
            if r.status_code == 200:
                return r.content
            last = RuntimeError(f"HTTP {r.status_code} for {url}")
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(1.5 * (i + 1))
    raise last
