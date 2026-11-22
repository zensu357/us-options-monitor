"""Yahoo 期权接口(crumb 配方):个股/ETF 篮子的成交量 P/C 代理。

CBOE delayed quotes 只放行指数链(_SPX),ETF/个股链一律 403,故篮子
P/C 改走 Yahoo v7 options API:fc.yahoo.com 取 A3 cookie → getcrumb →
v7 options。这里只聚合成交量(口径为近端到期),不做 greeks。
"""

import datetime
import time

import requests

from . import config, store

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

MAX_EXPIRIES = 6      # 近端 6 个到期覆盖日内成交主力
MAX_DTE = 60          # 只取 60 天内的到期
THROTTLE = 0.4        # 请求间隔(秒)


def _session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    s.get("https://fc.yahoo.com", timeout=15)          # 404 也无所谓,只为拿 cookie
    crumb = s.get("https://query1.finance.yahoo.com/v1/test/getcrumb",
                  timeout=15).text.strip()
    if not crumb or crumb.startswith("{"):
        raise RuntimeError(f"crumb 获取失败: {crumb[:60]}")
    return s, crumb


def _fetch_symbol(s, crumb, symbol):
    url = f"https://query2.finance.yahoo.com/v7/finance/options/{symbol}"
    r = s.get(url, params={"crumb": crumb}, timeout=15)
    r.raise_for_status()
    res = r.json()["optionChain"]["result"][0]
    expiries = [e for e in res["expirationDates"]
                if (e - time.time()) / 86400 <= MAX_DTE][:MAX_EXPIRIES]
    call_vol = put_vol = call_oi = put_oi = 0.0
    for e in expiries:
        time.sleep(THROTTLE)
        r2 = s.get(url, params={"crumb": crumb, "date": e}, timeout=15)
        r2.raise_for_status()
        opt = r2.json()["optionChain"]["result"][0]["options"][0]
        call_vol += sum(float(c.get("volume") or 0) for c in opt["calls"])
        put_vol += sum(float(p.get("volume") or 0) for p in opt["puts"])
        call_oi += sum(float(c.get("openInterest") or 0) for c in opt["calls"])
        put_oi += sum(float(p.get("openInterest") or 0) for p in opt["puts"])
    return {"call_vol": call_vol, "put_vol": put_vol,
            "call_oi": call_oi, "put_oi": put_oi}


def collect_basket(symbols=None, day=None):
    """聚合篮子各符号的近端成交量,写 chain_metrics(__BASKET__ 行)。"""
    symbols = symbols or config.EQ_BASKET
    day = day or datetime.date.today()
    try:
        s, crumb = _session()
    except Exception as e:  # noqa: BLE001
        print(f"  [yahoo-opt] 会话建立失败: {e}")
        return None
    total = {"call_vol": 0.0, "put_vol": 0.0, "call_oi": 0.0, "put_oi": 0.0}
    n_ok = 0
    for sym in symbols:
        try:
            m = _fetch_symbol(s, crumb, sym)
        except Exception as e:  # noqa: BLE001
            print(f"  [yahoo-opt] {sym} 失败: {e}")
            continue
        for k in total:
            total[k] += m[k]
        n_ok += 1
        print(f"  [yahoo-opt] {sym:<6} call={m['call_vol']:.0f} put={m['put_vol']:.0f}")
    if n_ok == 0:
        return None
    row = {
        "date": day.isoformat(),
        "symbol": "__BASKET__",
        "n_symbols": n_ok,
        "call_vol": total["call_vol"],
        "put_vol": total["put_vol"],
        "call_oi": total["call_oi"],
        "put_oi": total["put_oi"],
        "pc_vol": round(total["put_vol"] / total["call_vol"], 4) if total["call_vol"] else None,
        "pc_oi": round(total["put_oi"] / total["call_oi"], 4) if total["call_oi"] else None,
    }
    store.upsert("chain_metrics", [row], key=("date", "symbol"))
    print(f"  [yahoo-opt] BASKET({n_ok}/{len(symbols)}) P/C(vol)={row['pc_vol']}")
    return row
