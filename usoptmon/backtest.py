"""事件研究:用 Yahoo 长历史复现原版触发条件,统计触发后的前瞻收益/波动。

P/C 与 GEX 无免费历史,事件定义仅用波动率指数子集;结论是"叙事是否
有统计痕迹"的粗检,不是策略回测。
"""

import csv
import math
import statistics

from . import config, yahoo

HORIZONS = (1, 5, 10, 21)
MIN_GAP = 5          # 同类事件去重的最小间隔(交易日)
LOOKBACK_VOL = 30    # s4_reset 要求前期恐慌的回看窗口(交易日)


def load_history():
    """抓 max 历史并对齐为按日期排序的行列表。"""
    tables = {}
    for sym, col in config.YAHOO_SYMBOLS.items():
        if sym == "NVDA":
            continue
        try:
            rows = yahoo.fetch_history(sym, years=10)
        except Exception as e:  # noqa: BLE001
            print(f"  [backtest] {sym} 失败: {e}")
            continue
        for day, c in rows:
            tables.setdefault(day, {})[col] = c
        print(f"  [backtest] {col:<6} {len(rows)} rows")
    dates = sorted(d for d, v in tables.items() if "vix" in v and "spx" in v)
    return dates, tables


def build_events(dates, tables):
    """返回 {event_name: [row_index, ...]}(已按最小间隔去重)。"""
    n = len(dates)
    col = lambda i, k: tables[dates[i]].get(k)  # noqa: E731

    def ratio(i, a, b):
        x, y = col(i, a), col(i, b)
        if x and y:
            return x / y
        return None

    events = {
        "s3_vanna": [],
        "s3_confluence": [],
        "s4_reset": [],
        "skew_crowd": [],
    }
    last = {k: -999 for k in events}
    vix_hist = []
    for i, d in enumerate(dates):
        vix = col(i, "vix")
        vix_hist.append(vix or 0)
        term = ratio(i, "vix", "vix3m")
        vvix = col(i, "vvix")
        skew = col(i, "skew")

        def fire(name, cond):
            if cond and i - last[name] >= MIN_GAP:
                events[name].append(i)
                last[name] = i

        if term is not None and vvix is not None and vix:
            fire("s3_vanna", vix >= 28 and (term >= 1.0 or vvix >= 110))
            fire("s3_confluence", vix >= 26 and term >= 1.0 and vvix >= 110)
            prior_pan = (len(vix_hist) > LOOKBACK_VOL
                         and max(vix_hist[-LOOKBACK_VOL - 1:-1]) >= 26)
            fire("s4_reset", term < 1.0 and vvix < 110 and vix < 25 and prior_pan)
        if skew is not None and vix:
            fire("skew_crowd", skew >= 160 and vix < 25)
    return events


def forward_stats(dates, tables, idxs, horizon):
    """触发日后 horizon 交易日的 SPX 前瞻收益列表。"""
    out = []
    for i in idxs:
        j = i + horizon
        if j >= len(dates):
            continue
        p0, p1 = tables[dates[i]]["spx"], tables[dates[j]]["spx"]
        if p0 and p1:
            out.append(p1 / p0 - 1.0)
    return out


def _fmt_row(name, rets, baseline):
    if not rets:
        return f"{name:<14} n=0"
    mean = statistics.mean(rets)
    med = statistics.median(rets)
    pos = 100.0 * sum(r > 0 for r in rets) / len(rets)
    bmean = statistics.mean(baseline)
    bpos = 100.0 * sum(r > 0 for r in baseline) / len(baseline)
    return (f"{name:<14} n={len(rets):<4} mean={mean:+.3%} (基线 {bmean:+.3%})  "
            f"median={med:+.3%}  P(涨)={pos:.0f}% (基线 {bpos:.0f}%)  "
            f"worst={min(rets):+.2%}  best={max(rets):+.2%}")


def run():
    dates, tables = load_history()
    if len(dates) < 100:
        print("  [backtest] 历史不足,放弃")
        return
    events = build_events(dates, tables)

    # 无条件基线(全样本各 horizon)
    baseline = {h: forward_stats(dates, tables, list(range(len(dates))), h)
                for h in HORIZONS}

    # 触发后 21 日已实现波动(日收益标准差年化)
    def fwd_vol(i):
        rets = []
        for j in range(i + 1, min(i + 22, len(dates))):
            p0, p1 = tables[dates[j - 1]]["spx"], tables[dates[j]]["spx"]
            if p0 and p1:
                rets.append(math.log(p1 / p0))
        if len(rets) < 10:
            return None
        return statistics.stdev(rets) * math.sqrt(252)

    print("\n=== 前瞻收益(事件触发日 → h 交易日) ===")
    for name, idxs in events.items():
        if not idxs:
            print(f"{name:<14} n=0")
            continue
        for h in HORIZONS:
            rets = forward_stats(dates, tables, idxs, h)
            print(_fmt_row(f"{name}@h{h}", rets, baseline[h]))
    print("\n=== 触发后 21 日年化已实现波动(事件均值 vs 全样本均值) ===")
    all_vols = [v for v in (fwd_vol(i) for i in range(len(dates))) if v]
    base_v = statistics.mean(all_vols) if all_vols else float("nan")
    for name, idxs in events.items():
        vs = [v for v in (fwd_vol(i) for i in idxs) if v]
        if vs:
            print(f"{name:<14} n={len(vs):<4} mean={statistics.mean(vs):.1%}  (基线 {base_v:.1%})")

    # 事件明细落盘
    path = config.DATA / "backtest_events.csv"
    config.DATA.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["event", "date", "vix", "vix_vix3m", "vvix", "skew"])
        for name, idxs in events.items():
            for i in idxs:
                t = tables[dates[i]]
                w.writerow([name, dates[i], t.get("vix"), t.get("vix3m"),
                            t.get("vvix"), t.get("skew")])
    print(f"\n  事件明细 -> {path}")
    return {"dates": dates, "events": events, "tables": tables}
