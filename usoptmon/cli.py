"""CLI:python3 -m usoptmon <collect|score|report|backtest|run>"""

import argparse
import datetime

from . import backtest, cboe, config, report, stress, store, yahoo


def _latest_chain_rows(day_iso, _cache={"loaded": False, "rows": None}):
    """取指定日期的 SPX / 篮子汇总 chain_metrics 行(整表仅读一次)。"""
    if not _cache["loaded"]:
        _cache["rows"] = store.read("chain_metrics")
        _cache["loaded"] = True
    spx = basket = None
    for r in _cache["rows"] or []:
        if r.get("date") != day_iso:
            continue
        if r.get("symbol") == "SPX":
            spx = r
        elif r.get("symbol") == "__BASKET__":
            basket = r
    return spx, basket


def _basket_summary(chains):
    """已废弃:CBOE 只放行指数链,篮子改由 yahoo_options.collect_basket 采集。"""
    return None


def _latest_trade_day():
    """最新交易日:取 vol_indexes 里带 SPX 收盘的最近日期(周六运行=周五)。"""
    days = [r["date"] for r in store.read("vol_indexes") if r.get("spx")]
    return max(days) if days else datetime.date.today().isoformat()


def cmd_collect(args):
    print("[collect] Yahoo 波动率指数…")
    yahoo.collect(years=args.years)
    if args.light:
        return
    trade_day = datetime.date.fromisoformat(_latest_trade_day())
    print(f"[collect] 数据交易日 = {trade_day}")
    print("[collect] CBOE SPX 期权链(指数链才有公开 ACL)…")
    cboe.collect_chains(["SPX"], day=trade_day, keep_raw=not args.no_raw)
    print("[collect] Yahoo 期权接口:个股篮子 P/C…")
    from . import yahoo_options
    yahoo_options.collect_basket(day=trade_day)


def _chain_rows_for_date(day_iso):
    """当日常规行 + 从 raw 缓存重建篮子行(报告日 = 采集日时直接读内存外缓存)。"""
    spx, basket = _latest_chain_rows(day_iso)
    return spx, basket


def cmd_score(args):
    vol = store.read("vol_indexes")
    if not vol:
        print("[score] vol_indexes.csv 为空,先运行 collect")
        return
    chain_days = {r["date"] for r in store.read("chain_metrics")}

    # 1) 全历史逐日打分(缺链数据的日期自动归一为"仅波动率"口径)
    score_rows = []
    for r in vol:
        d = r["date"]
        spx_row, basket_row = _chain_rows_for_date(d)
        snap = stress.build_snapshot(r, spx_row, basket_row)
        score_rows.append({
            "date": d,
            "stress": snap["stress"] if snap["stress"] is not None else "",
            "stage": snap["regime"]["stage"],
            "regime_title": snap["regime"]["title"],
            "macro_defense": int(snap["regime"]["macroDefense"]),
            **{k: ("" if snap.get(k) is None else snap.get(k))
               for k in ("vix", "vvix", "vix9dvix", "vixvxv", "skew", "dspx",
                         "vixeqVix", "nvda", "spxGex", "dealerGamma", "netDelta",
                         "pc_eq", "pc_total", "pc_idx")},
            "risk_hits": sum(1 for it in snap["checklists"]["risk"] if it["triggered"]),
            "reset_hits": sum(1 for it in snap["checklists"]["reset"] if it["triggered"]),
        })
    store.write("scores", score_rows)
    print(f"[score] scores.csv 共 {len(score_rows)} 行(链数据仅覆盖最近 {len(chain_days)} 日)")

    # 2) 最新一日控制台摘要
    latest = score_rows[-1]
    print(f"\n=== {latest['date']} ===")
    print(f"  压力指数: {latest['stress'] or '--'}/100   阶段: {latest['regime_title']}")
    for k, label, _t, _n in (it for g in stress.INDICATOR_GROUPS for it in g[1]):
        v = latest.get(k, "")
        print(f"  {label:<26} {v if v != '' else '--'}")
    print(f"  风险触发 {latest['risk_hits']}/4 · 修复触发 {latest['reset_hits']}/4")


def cmd_report(args):
    vol = {r["date"]: r for r in store.read("vol_indexes")}
    if not vol:
        print("[report] 无数据,先运行 collect")
        return
    day = args.date or max(vol)
    spx_row, basket_row = _chain_rows_for_date(day)
    snap = stress.build_snapshot(vol[day], spx_row, basket_row)
    quote_ts = ""
    cm = [r for r in store.read("chain_metrics") if r.get("date") == day and r.get("symbol") == "SPX"]
    if cm:
        quote_ts = cm[0].get("quote_ts") or ""
    path = report.render(snap, day, quote_ts=quote_ts)
    print(f"[report] {path}")


def cmd_backtest(args):
    backtest.run()


def cmd_watch(args):
    import os

    from . import watch
    notify = args.notify or os.environ.get("USOPTMON_NOTIFY")
    webhook = args.webhook or os.environ.get("USOPTMON_WEBHOOK")
    watch.watch_once(use_chain=not args.no_chain, use_basket=args.basket,
                     notify_channel=notify, notify_url=webhook)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="usoptmon", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("collect", help="采集 Yahoo 指数 + CBOE 期权链")
    p.add_argument("--years", type=int, default=2, help="Yahoo 历史年数(默认 2)")
    p.add_argument("--light", action="store_true", help="仅采指数,跳过期权链")
    p.add_argument("--no-raw", action="store_true", help="不落原始链 JSON(CI 用)")
    p.set_defaults(fn=cmd_collect)

    sub.add_parser("score", help="计算压力指数/regime/checklist 并写 scores.csv").set_defaults(fn=cmd_score)
    p = sub.add_parser("report", help="渲染每日 HTML 报告")
    p.add_argument("--date", default=None, help="报告日期(默认最新)")
    p.set_defaults(fn=cmd_report)
    sub.add_parser("backtest", help="事件研究回测").set_defaults(fn=cmd_backtest)

    p = sub.add_parser("run", help="全流程 collect + score + report")
    p.add_argument("--years", type=int, default=2)
    p.add_argument("--light", action="store_true")
    p.add_argument("--no-raw", action="store_true")
    p.add_argument("--date", default=None, help="报告日期(默认最新)")
    p.set_defaults(fn=None)

    p = sub.add_parser("watch", help="修复信号盯盘(边缘触发告警)")
    p.add_argument("--no-chain", action="store_true", help="跳过 SPX 链(轻量巡检,R1 缺席)")
    p.add_argument("--basket", action="store_true", help="顺带更新篮子 P/C(约 40 个请求)")
    p.add_argument("--notify", default=None, choices=["feishu", "bark", "generic", "mail"])
    p.add_argument("--webhook", default=None, help="webhook 地址(bark 填 key 即可)")
    p.set_defaults(fn=cmd_watch)

    args = ap.parse_args(argv)
    if args.cmd == "run":
        cmd_collect(args)
        cmd_score(args)
        cmd_report(args)
    else:
        args.fn(args)


if __name__ == "__main__":
    main()
