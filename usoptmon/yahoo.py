"""Yahoo chart API:免费拉取波动率指数与 SPX/NVDA 的日线历史。"""

import datetime

from . import config, net, store

BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{}"


def fetch_history(symbol, years=2):
    """返回 list[(date, close)],剔除停牌/空值。

    用 period1/period2 分段拉取:Yahoo 对 range=max 会静默降级为季度线,
    period+interval=1d 才能拿到全部日线。
    """
    import time as _time

    now = int(_time.time())
    start = now - years * 365 * 86400
    step = 3 * 365 * 86400
    out = {}
    last_res = None
    while start < now:
        end = min(start + step, now)
        url = (f"{BASE_URL.format(symbol.replace('^', '%5E'))}"
               f"?period1={start}&period2={end}&interval=1d")
        try:
            d = net.get_json(url, headers=net.YAHOO_HEADERS)
            res = d["chart"]["result"][0]
        except Exception as e:  # noqa: BLE001 - 单段失败跳过(如 DSPX 上线前的区间 400)
            print(f"  [yahoo] {symbol} 分段 {end - start} 跳过: {e}")
            start = end
            continue
        last_res = res
        ts = res.get("timestamp") or []
        closes = res["indicators"]["quote"][0].get("close") or []
        for t, c in zip(ts, closes):
            if c is None:
                continue
            day = datetime.datetime.fromtimestamp(t, tz=datetime.timezone.utc).date()
            out[day.isoformat()] = float(c)
        start = end
    # meta 里兜底取最新价(个别指数如 ^VIXEQ 历史只有 1 行)
    if not out and last_res is not None:
        price = last_res["meta"].get("regularMarketPrice")
        if price:
            out[datetime.date.today().isoformat()] = float(price)
    return sorted(out.items())


def collect(years=2, symbols=None):
    """抓全部指数历史并 upsert 进 vol_indexes.csv(宽表,date 为键)。"""
    symbols = symbols or config.YAHOO_SYMBOLS
    tables = {}
    for sym, col in symbols.items():
        try:
            rows = fetch_history(sym, years=years)
        except Exception as e:  # noqa: BLE001 - 单符号失败不阻塞整体
            print(f"  [yahoo] {sym} 失败: {e}")
            continue
        for day, c in rows:
            tables.setdefault(day, {})[col] = c
        print(f"  [yahoo] {sym:<8} -> {col:<6} {len(rows)} rows")
    records = [{"date": day, **vals} for day, vals in sorted(tables.items())]
    n = store.upsert("vol_indexes", records)
    print(f"  [yahoo] vol_indexes.csv 合计 {n} 行")
    return records
