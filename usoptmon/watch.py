"""修复信号盯盘(watch):边缘触发的告警 + 可选推送。

与每日报告互补:报告是收盘后全量快照;watch 是轻量巡检——
只盯"止跌与重置确认项"四条 + 风险面回撤,状态翻转才告警。

信号定义(与 stress.checklists.reset 一致):
  R1  GEX 收窄至 -30B 以上 且 Net Delta 回正     —— 需 SPX 链(--no-chain 时跳过)
  R2  VVIX < 110(尾部挤兑降温)                —— Yahoo 实时
  R3  VIX/VIX3M 与 VIX9D/VIX 双双 <1.00(解除倒挂)—— Yahoo 实时
  R4  VIXEQ/VIX >=1.70 且 VIX <25(离散止血)     —— Yahoo 实时
复合:R1~R4 同时成立 >=3 条 => "修复确认"强告警。
"""

import csv
import datetime
import json

import requests

from . import config, net, stress, store
from .cboe import fetch_chain, parse_chain
from .gex import chain_metrics

SPOT_SYMBOLS = {
    "^VIX": "vix", "^VIX9D": "vix9d", "^VIX3M": "vix3m",
    "^VVIX": "vvix", "^SKEW": "skew", "^DSPX": "dspx", "^VIXEQ": "vixeq",
}

RESET_SIGNAL_NAMES = [
    "R1_GEX重置回拉", "R2_VVIX降温", "R3_倒挂解除", "R4_离散止血",
]


# ---------------------------------------------------------------- 实时价
def _spot(symbol):
    """Yahoo 实时/最近收盘价(延迟分钟级,盯信号足够)。"""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{symbol.replace('^', '%5E')}?range=1d&interval=1d")
    res = net.get_json(url, headers=net.YAHOO_HEADERS)["chart"]["result"][0]
    closes = res["indicators"]["quote"][0].get("close") or []
    close = next((c for c in reversed(closes) if c is not None), None)
    if close is None:
        close = res["meta"].get("regularMarketPrice")
    return float(close) if close is not None else None


def _trade_day(ts_str):
    """CBOE 链快照时间戳(UTC)→ 美东交易日,避免周末/隔夜错位。"""
    try:
        from zoneinfo import ZoneInfo
        dt = datetime.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    except Exception:  # noqa: BLE001
        return datetime.date.today().isoformat()


def _next_opex(day):
    """下一个美股月度 OPEX(当月第三个周五;已过则顺延下月)。"""
    def third_friday(y, m):
        d = datetime.date(y, m, 1)
        return d + datetime.timedelta(days=(4 - d.weekday()) % 7 + 14)
    tf = third_friday(day.year, day.month)
    if tf <= day:
        m = day.month + 1
        tf = third_friday(day.year + (m > 12), (m - 1) % 12 + 1)
    return tf


# ---------------------------------------------------------------- 告警状态
def _state_path():
    config.DATA.mkdir(parents=True, exist_ok=True)
    return config.DATA / "alert_state.json"


def _load_state():
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"signals": {}, "strong_on": False}


def _save_state(state):
    _state_path().write_text(
        json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def _append_alerts(rows):
    if not rows:
        return
    p = config.DATA / "alerts.csv"
    new_file = not p.exists()
    with open(p, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["ts", "trade_day", "signal", "kind", "detail"])
        w.writerows(rows)


# ---------------------------------------------------------------- 推送
def _send_mail(subject, body):
    """SMTP 发信(零依赖 smtplib)。

    环境变量:USOPTMON_SMTP_HOST / USOPTMON_SMTP_PORT(465=SSL,587=STARTTLS)
    / USOPTMON_SMTP_USER / USOPTMON_SMTP_PASS(授权码,非登录密码)
    / USOPTMON_MAIL_TO(逗号分隔多收件人)。
    """
    import os
    import smtplib
    from email.header import Header
    from email.mime.text import MIMEText

    host = os.environ.get("USOPTMON_SMTP_HOST")
    user = os.environ.get("USOPTMON_SMTP_USER")
    pwd = os.environ.get("USOPTMON_SMTP_PASS")
    to = [x.strip() for x in (os.environ.get("USOPTMON_MAIL_TO") or "").split(",")
          if x.strip()]
    if not (host and user and pwd and to):
        print("  [watch] 邮件未发送:需配置 USOPTMON_SMTP_HOST/USER/PASS/MAIL_TO"
              "(QQ/163 用授权码,Gmail 用应用专用密码)")
        return
    port = int(os.environ.get("USOPTMON_SMTP_PORT") or "465")
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = user
    msg["To"] = ",".join(to)
    try:
        if port == 465:
            s = smtplib.SMTP_SSL(host, port, timeout=15)
        else:
            s = smtplib.SMTP(host, port, timeout=15)
            s.starttls()
        with s:
            s.login(user, pwd)
            s.sendmail(user, to, msg.as_string())
        print(f"  [watch] 邮件已发送 -> {', '.join(to)}")
    except Exception as e:  # noqa: BLE001 - 推送失败不阻塞巡检
        print(f"  [watch] 邮件发送失败: {e}")


def _notify(message, channel, url):
    if not channel:
        return
    if channel == "mail":
        lines = [ln for ln in message.splitlines() if ln.strip()]
        detail = lines[1] if len(lines) > 1 else "状态更新"
        _send_mail(f"[期权修复盯盘] {detail}"[:78], message)
        return
    if not url:
        return
    try:
        if channel == "feishu":
            requests.post(url, timeout=10, json={
                "msg_type": "text", "content": {"text": message}})
        elif channel == "bark":
            if not url.startswith("http"):
                url = f"https://api.day.app/{url}"
            requests.get(f"{url}/{requests.utils.quote(message)}", timeout=10)
        else:  # generic
            requests.post(url, timeout=10, json={"text": message})
    except Exception as e:  # noqa: BLE001 - 推送失败不阻塞巡检
        print(f"  [watch] 推送失败({channel}): {e}")


# ---------------------------------------------------------------- 主巡检
def watch_once(use_chain=True, use_basket=False, notify_channel=None, notify_url=None,
               force_notify=False):
    now = datetime.datetime.now()

    # 1) 实时指数
    vol_row = {}
    for sym, col in SPOT_SYMBOLS.items():
        try:
            v = _spot(sym)
            if v is not None:
                vol_row[col] = v
        except Exception as e:  # noqa: BLE001
            print(f"  [watch] {sym} 失败: {e}")

    # 2) SPX 链(可选)
    spx_m = basket_m = None
    chain_note = "未拉链(--no-chain)"
    if use_chain:
        try:
            payload = fetch_chain("SPX")
            rows, snap = parse_chain(payload)
            spx_m = chain_metrics(rows, snap["spot"])
            spx_m["symbol"] = "SPX"
            spx_m["date"] = _trade_day(snap.get("quote_ts") or "")
            spx_m["quote_ts"] = snap.get("quote_ts") or ""
            store.upsert("chain_metrics", [spx_m], key=("date", "symbol"))
            chain_note = f"链快照交易日 {spx_m['date']}"
        except Exception as e:  # noqa: BLE001
            print(f"  [watch] SPX 链失败: {e}")
    if use_basket:
        from . import yahoo_options
        basket_m = yahoo_options.collect_basket(
            day=datetime.date.today())

    # 3) 快照与信号
    snap = stress.build_snapshot(vol_row, spx_m, basket_m)
    if spx_m:
        day_iso = spx_m["date"]
    else:
        # 无链模式:取"当前所属美股交易日"——美东工作日且已过 UTC 12:00
        # 即视为当日(盘前到盘后全覆盖);否则回退到最近有 SPX 收盘的日期。
        # 节假日无法自检,会显示当日,属可接受的轻微偏差。
        from zoneinfo import ZoneInfo
        et = datetime.datetime.now(ZoneInfo("America/New_York"))
        is_us_day = et.weekday() < 5 and now.hour >= 12
        if is_us_day:
            day_iso = et.date().isoformat()
        else:
            spx_days = [r["date"] for r in store.read("vol_indexes") if r.get("spx")]
            day_iso = max(spx_days) if spx_days else et.date().isoformat()
    reset = snap["checklists"]["reset"]
    risk_hits = sum(1 for it in snap["checklists"]["risk"] if it["triggered"])
    reset_hits = sum(1 for it in reset if it["triggered"])
    signals = {name: bool(it["triggered"])
               for name, it in zip(RESET_SIGNAL_NAMES, reset)}
    strong = reset_hits >= 3

    # 4) 边缘触发判定
    state = _load_state()
    alert_rows = []
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    for name, on in signals.items():
        prev = state["signals"].get(name)
        prev_on = bool(prev and prev.get("on"))
        if on and not prev_on:
            kind, mark = "new", "🟢 新触发"
        elif on and prev_on and (prev.get("last_day") != day_iso):
            kind, mark = "persist", "🔔 持续成立(每日提醒一次)"
        elif (not on) and prev_on:
            kind, mark = "off", "⚪ 回落"
        else:
            continue
        alert_rows.append([ts, day_iso, name, kind, f"{mark} {name}"])
        state["signals"][name] = {"on": on, "last_day": day_iso}
    if strong and not state.get("strong_on"):
        alert_rows.append([ts, day_iso, "COMPOSITE_修复确认",
                           "new", f"✅ 修复确认 {reset_hits}/4 — 历史基率:触发后 21 日均值 +4.3%、胜率 83%(见 README 回测)"])
    elif (not strong) and state.get("strong_on"):
        alert_rows.append([ts, day_iso, "COMPOSITE_修复确认", "off", "修复确认失效(<3/4)"])
    state["strong_on"] = strong
    _save_state(state)
    _append_alerts(alert_rows)

    # 5) 输出状态板
    opex = _next_opex(now.date())
    print(f"\n=== [watch] {ts}  交易日 {day_iso}  ({chain_note}) ===")
    print(f"  VIX {vol_row.get('vix', '--')} | VVIX {vol_row.get('vvix', '--')} | "
          f"VIX/VIX3M {snap.get('vixvxv', '--')} | VIX9D/VIX {snap.get('vix9dvix', '--')} | "
          f"GEX {(spx_m or {}).get('gex_b', '--')}B | NetDelta {(spx_m or {}).get('netdelta_proxy', '--')}")
    print(f"  修复确认 {reset_hits}/4 · 风险面 {risk_hits}/4 · "
          f"距下次月度 OPEX {opex.isoformat()} 还有 {(opex - now.date()).days} 天(日历减压阀)")
    for name, it in zip(RESET_SIGNAL_NAMES, reset):
        print(f"  [{'✅' if it['triggered'] else '· '}] {name:<14} {it['text']}")
    if alert_rows:
        print(f"  >>> {len(alert_rows)} 条告警 -> data/alerts.csv")
    else:
        print("  (状态无翻转,无新告警)")

    # 6) 推送
    board_lines = [f"[{'✅' if it['triggered'] else '· '}] {name}  {it['text']}"
                   for name, it in zip(RESET_SIGNAL_NAMES, reset)]
    board = "\n".join([
        f"交易日 {day_iso}({chain_note})",
        f"VIX {vol_row.get('vix', '--')} | VVIX {vol_row.get('vvix', '--')} | "
        f"VIX/VIX3M {snap.get('vixvxv', '--')} | GEX {(spx_m or {}).get('gex_b', '--')}B",
        f"修复 {reset_hits}/4 · 风险 {risk_hits}/4 · "
        f"距 OPEX {opex.isoformat()} 还有 {(opex - now.date()).days} 天",
        *board_lines,
    ])
    if notify_channel and alert_rows:
        msg = (f"[期权修复盯盘 {ts}]\n"
               + "\n".join(r[4] for r in alert_rows) + "\n" + board)
        _notify(msg, notify_channel, notify_url)
    elif notify_channel and force_notify:
        # --test:无翻转也发一条状态板,验证推送通路
        _notify(f"[期权修复盯盘·通路测试 {ts}]\n(无新翻转,此为状态板)\n{board}",
                notify_channel, notify_url)
    return {"reset_hits": reset_hits, "risk_hits": risk_hits,
            "signals": signals, "alerts": alert_rows}
