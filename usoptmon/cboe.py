"""CBOE delayed quotes:期权链下载 / 解析 / 原始缓存。"""

import datetime
import json
import re

from . import config, net, store

CHAIN_URL = "https://cdn-api.cboe.com/api/global/delayed_quotes/options/_{}.json"

SYM_RE = re.compile(r"^([A-Z0-9]+?)(\d{6})([CP])(\d{8})$")


def fetch_chain(symbol):
    """下载期权链 JSON(带完整浏览器头)。"""
    url = CHAIN_URL.format(symbol)
    raw = net.get_bytes(url, headers=net.CBOE_HEADERS)
    return json.loads(raw)


def parse_chain(data):
    """把链 JSON 解析为规整的期权行列表 + 标的快照。

    期权行: dict(expiry, cp, strike, gamma, delta, oi, volume, iv, bid, ask)
    仅保留 gamma/delta 有效且 (oi>0 或 volume>0) 的合约。
    """
    root = data["data"]
    spot = float(root.get("current_price") or 0)
    rows = []
    for o in root["options"]:
        oi = o.get("open_interest") or 0
        vol = o.get("volume") or 0
        if oi <= 0 and vol <= 0:
            continue
        m = SYM_RE.match(o["option"])
        if not m:
            continue
        gamma = o.get("gamma") or 0
        delta = o.get("delta") or 0
        if gamma == 0 and delta == 0:
            continue
        _, ymd, cp, k = m.groups()
        rows.append({
            "expiry": f"20{ymd[:2]}-{ymd[2:4]}-{ymd[4:6]}",
            "cp": cp,
            "strike": int(k) / 1000.0,
            "gamma": float(gamma),
            "delta": float(delta),
            "oi": float(oi),
            "volume": float(vol),
            "iv": float(o.get("iv") or 0),
            "bid": float(o.get("bid") or 0),
            "ask": float(o.get("ask") or 0),
        })
    snapshot = {
        "spot": spot,
        "spx_iv30": float(root.get("iv30") or 0),
        "quote_ts": data.get("timestamp"),
    }
    return rows, snapshot


def save_raw(symbol, payload, day):
    d = config.RAW / day.isoformat()
    d.mkdir(parents=True, exist_ok=True)
    with open(d / f"{symbol}.json", "w", encoding="utf-8") as f:
        json.dump(payload, f)


def collect_chains(symbols, day=None, keep_raw=True):
    """抓指定符号的链,计算链级指标并 upsert 进 chain_metrics.csv。

    返回 {symbol: (rows, snapshot)};单符号失败跳过不阻塞。
    """
    from . import gex

    day = day or datetime.date.today()
    out = {}
    metrics_rows = []
    for i, sym in enumerate(symbols):
        if i:
            import time
            time.sleep(3)  # Cloudflare 频控:链与链之间留间隔
        try:
            payload = fetch_chain(sym)
            rows, snap = parse_chain(payload)
        except Exception as e:  # noqa: BLE001
            print(f"  [cboe] {sym} 失败: {e}")
            continue
        out[sym] = (rows, snap)
        if keep_raw:
            save_raw(sym, payload, day)
        m = gex.chain_metrics(rows, snap["spot"])
        m["date"] = day.isoformat()
        m["symbol"] = sym
        metrics_rows.append(m)
        print(f"  [cboe] {sym:<5} {len(rows):>6} 合约  spot={snap['spot']:.2f}  "
              f"GEX={m.get('gex_b', 0):+.1f}B  P/C(vol)={m.get('pc_vol', 0):.3f}")
    if metrics_rows:
        store.upsert("chain_metrics", metrics_rows, key=("date", "symbol"))
    store.prune_raw(config.KEEP_RAW_DAYS)
    return out
