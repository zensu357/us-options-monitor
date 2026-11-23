"""核心逻辑:14 指标状态灯 / 综合压力指数 / regime 状态机 / 双向 checklist。

所有阈值与权重移植自付鹏仪表盘原版;NaN 容错:缺数据的分项跳过并重新归一。
"""

import math

from . import config


def _f(v):
    try:
        v = float(v)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ---------------------------------------------------------------- 14 指标元数据
# (key, 名称, 红线描述) —— status: red / amber / green / na
def eval_indicator(key, s):
    t = config.THRESHOLDS
    if key == "vixeqVix":
        v = _f(s.get("vixeqVix"))
        if v is None:
            return "na"
        return "red" if v < t["vixeq_red_low"] else ("amber" if v < t["vixeq_amber_low"] else "green")
    if key == "dspx":
        v, vix = _f(s.get("dspx")), _f(s.get("vix")) or 0
        if v is None:
            return "na"
        if v < t["dspx_red"] and vix > t["skew_red_vix_gate"]:
            return "red"
        return "amber" if v < t["dspx_amber"] else "green"
    if key == "nvda":
        v = _f(s.get("nvda"))
        if v is None:
            return "na"
        return "red" if v < t["nvda_red"] else ("amber" if v < t["nvda_amber"] else "green")
    if key == "vix":
        v = _f(s.get("vix"))
        if v is None:
            return "na"
        return "red" if v >= t["vix_red"] else ("amber" if v >= t["vix_amber"] else "green")
    if key == "vvix":
        v = _f(s.get("vvix"))
        if v is None:
            return "na"
        return "red" if v >= t["vvix_red"] else ("amber" if v >= t["vvix_amber"] else "green")
    if key in ("vixvxv", "vix9dvix"):
        v = _f(s.get(key))
        if v is None:
            return "na"
        return "red" if v > t["term_red"] else ("amber" if v >= t["term_amber"] else "green")
    if key == "skew":
        v, vix = _f(s.get("skew")), _f(s.get("vix")) or 0
        if v is None:
            return "na"
        if v >= t["skew_amber_high"]:
            return "amber"
        if vix >= t["skew_red_vix_gate"] and v < t["skew_red_below"]:
            return "red"
        return "green"
    if key == "pc_eq":
        v = _f(s.get("pc_eq"))
        if v is None:
            return "na"
        return "red" if v >= t["pc_eq_red"] else ("amber" if v >= t["pc_eq_amber"] else "green")
    if key == "pc_total":
        v = _f(s.get("pc_total"))
        if v is None:
            return "na"
        return "red" if v >= t["pc_total_red"] else ("amber" if v >= t["pc_total_amber"] else "green")
    if key == "pc_idx":
        v = _f(s.get("pc_idx"))
        if v is None:
            return "na"
        return "red" if v >= t["pc_idx_red"] else ("amber" if v >= t["pc_idx_amber"] else "green")
    if key == "spxGex":
        v = _f(s.get("spxGex"))
        if v is None:
            return "na"
        return "red" if v <= t["gex_red"] else ("amber" if v < 0 else "green")
    if key == "dealerGamma":
        # naive 口径下 dealerGamma 与 SPX GEX 同值,$B per 1% move。
        # 不可与 Squeezemetrics 的 -8.6B 底线混用(量纲不同),故用同尺度阈值。
        v = _f(s.get("dealerGamma"))
        if v is None:
            return "na"
        return "red" if v <= t["gex_red"] else ("amber" if v < 0 else "green")
    if key == "netDelta":
        v = _f(s.get("netDelta"))
        if v is None:
            return "na"
        return "red" if v <= t["netdelta_red"] else ("amber" if v < 0 else "green")
    return "na"


# 指标展示顺序与标签(五个维度)
INDICATOR_GROUPS = [
    ("一、离散与相关性", [("vixeqVix", "VIXEQ / VIX", "红线 <1.85(高位断崖回落)", "proxy:VIXEQ 历史极短"),
                     ("dspx", "DSPX 离散度指数", "<35 且 VIX>25 为红(相关性飙升)", ""),
                     ("nvda", "NVDA 风向标", "<148 红 / <160 警戒(上升通道考验)", "")]),
    ("二、波动率与流动性挤兑", [("vix", "VIX 30D", "红线 >28(触发 Vanna)", ""),
                          ("vvix", "VVIX", "红线 >=115(对冲工具挤兑)", "")]),
    ("三、期限结构与偏度", [("vixvxv", "VIX / VIX3M", ">1.00 红(Backwardation)", "VIX3M 即原版 VXV"),
                       ("vix9dvix", "VIX9D / VIX", ">1.00 红(超短端反超)", ""),
                       ("skew", "CBOE SKEW", "160~170 警戒;VIX>=25 且 <150 红", "")]),
    ("四、期权流量 P/C", [("pc_eq", "个股 P/C(篮子)", "红线 >0.80(2022 式去杠杆)", "proxy:10 龙头篮子"),
                      ("pc_total", "综合 P/C", "红线 >1.25(全市场扩散)", "proxy:篮子+SPX 混合口径"),
                      ("pc_idx", "指数 P/C(SPX 链)", "红线 >1.25(宏观全面防御)", "proxy:CBOE 官方口径已失效")]),
    ("五、做市商敞口", [("spxGex", "SPX GEX(naive $B/1%)", "<=-50 红(原版极值 -97~-104)", "proxy:naive 口径"),
                    ("dealerGamma", "Dealer Agg Gamma", "<=-5 红;-8.6B 为他家历史底线,仅参考", "proxy:同 naive 口径"),
                    ("netDelta", "Net Delta Flow(代理)", "<=-40 红(重标定,原版 -60/150)", "proxy:看跌侧 delta 成交占比")]),
]

ALL_KEYS = [k for _, items in INDICATOR_GROUPS for k, _, _, _ in items]


# ---------------------------------------------------------------- 压力指数
def compute_stress(s):
    """原版权重;缺数据的分项按剩余权重归一化到 0-100。"""
    sc, rg = config.STRESS_SCALE, config.STRESS_RANGE
    total_w, acc = 0.0, 0.0

    def add(key):
        nonlocal total_w, acc
        v = _f(s.get(key))
        if v is None:
            return
        lo, hi = rg[key]
        if key in ("gex", "dealerGamma", "netDelta", "vixeqVix"):
            # 越负/越低越危险:区间已按危险方向正向化
            x = (hi - v) / (hi - lo)
        else:
            x = (v - lo) / (hi - lo)
        x = _clamp(x, 0.0, 1.0)
        w = sc[key]
        total_w += w
        acc += w * x

    add("vix"); add("vvix"); add("vixvxv"); add("vix9dvix")
    add("gex"); add("dealerGamma"); add("netDelta")
    add("vixeqVix")
    add("pc_eq"); add("pc_total"); add("pc_idx")
    if total_w == 0:
        return None
    return round(100.0 * acc / total_w)


# ---------------------------------------------------------------- regime 状态机
def detect_regime(s):
    """原版 if-then 状态机;返回 dict(stage, title, color, macroDefense)。缺数据按不满足处理。"""
    t, r = config.THRESHOLDS, config.REGIME
    g = {k: _f(s.get(k)) for k in
         ("vix", "vvix", "vixvxv", "spxGex", "dealerGamma", "netDelta",
          "skew", "vixeqVix", "pc_eq", "pc_idx")}

    pc_idx, pc_eq = g["pc_idx"], g["pc_eq"]
    macro = False
    if (pc_idx is not None and pc_eq is not None
            and pc_idx >= t["pc_idx_red"] and pc_eq >= t["pc_eq_red"]):
        macro = True
    # 深度负 Gamma 极值(naive 尺度;-8.6B 属他家口径,不可直接比较)
    if g["spxGex"] is not None and g["spxGex"] <= r["gex_extreme"]:
        macro = True

    dg, sg = g["dealerGamma"], g["spxGex"]
    cond_s3_vol = (g["vix"] is not None and g["vix"] >= r["s3_vix_gate"]
                   and (g["vixvxv"] is not None and g["vixvxv"] >= t["term_red"]
                        or g["vvix"] is not None and g["vvix"] >= t["vvix_red"]))
    cond_s3_gamma = sg is not None and sg <= t["gex_red"]
    if cond_s3_vol or cond_s3_gamma:
        title = ("阶段三升级:Vanna 踩踏与宏观全面防御" if macro
                 else "阶段三:负反馈翻转与 Vanna 踩踏加速期")
        return {"stage": 3, "title": title, "color": "red", "macroDefense": macro}

    if (dg is not None and sg is not None and g["vix"] is not None and g["skew"] is not None
            and dg >= r["s1_dealer_gamma"] and sg >= r["s1_gex"]
            and g["vix"] < r["s1_vix"] and g["skew"] < r["s1_skew"]):
        return {"stage": 1, "title": "阶段一:缩圈与离散稳态期",
                "color": "green", "macroDefense": False}

    if (g["vixvxv"] is not None and g["vvix"] is not None and g["skew"] is not None
            and g["netDelta"] is not None and g["spxGex"] is not None and g["vixeqVix"] is not None
            and g["vixvxv"] < t["term_red"] and g["vvix"] < t["vvix_red"]
            and g["skew"] < r["s4_skew"] and g["netDelta"] >= 0
            and g["spxGex"] < r["s4_gex"] and g["vixeqVix"] < r["s4_vixeq"]):
        return {"stage": 4, "title": "阶段四:极端出清与反向 Vanna 修复期",
                "color": "blue", "macroDefense": False}

    return {"stage": 2, "title": "阶段二:拥挤见顶与先遣撤退期",
            "color": "amber", "macroDefense": False}


# ---------------------------------------------------------------- 双向 checklist
def checklists(s):
    t = config.THRESHOLDS
    spx_gex = _f(s.get("spxGex"))

    def _spx_gex_reset():
        return spx_gex is not None and spx_gex > -30

    def _nd():
        v = _f(s.get("netDelta"))
        return v is not None and v >= 0

    risk = [
        ("个股 P/C >=0.80 且综合 P/C >=1.25", None,
         lambda: (_f(s.get("pc_eq")) or 0) >= t["pc_eq_red"]
                 and (_f(s.get("pc_total")) or 0) >= t["pc_total_red"]),
        ("指数 P/C 放量站稳 1.25 上方(宏观全面防御)", None,
         lambda: (_f(s.get("pc_idx")) or 0) >= t["pc_idx_red"]),
        ("SPX GEX 跌破 -100B/1%(深度负 Gamma 极值区)", None,
         lambda: (_f(s.get("spxGex")) or 0) <= config.REGIME["gex_extreme"]),
        ("VIX>28 且 VIX/VXV>1.00 且 VVIX>=110(Vanna 螺旋强化)", None,
         lambda: (_f(s.get("vix")) or 0) > t["vix_red"]
                 and (_f(s.get("vixvxv")) or 0) > t["term_red"]
                 and (_f(s.get("vvix")) or 0) >= 110),
    ]
    reset = [
        ("OPEX 重置:GEX 收窄至 -30B 以上且 Net Delta 回正", None,
         lambda: _spx_gex_reset() and _nd()),
        ("VVIX 回落至 110 下方(尾部挤兑降温)", None,
         lambda: (_f(s.get("vvix")) or 999) < 110),
        ("VIX/VXV 与 VIX9D/VIX 双双 <1.00(解除 Vanna 倒挂)", None,
         lambda: (_f(s.get("vixvxv")) or 9) < t["term_red"]
                 and (_f(s.get("vix9dvix")) or 9) < t["term_red"]),
        ("VIXEQ/VIX>=1.70 且 VIX<25(离散平仓止血)", None,
         lambda: (_f(s.get("vixeqVix")) or 0) >= 1.70 and (_f(s.get("vix")) or 99) < 25),
    ]
    return {
        "risk": [{"text": txt, "triggered": fn()} for txt, _, fn in risk],
        "reset": [{"text": txt, "triggered": fn()} for txt, _, fn in reset],
    }


# ---------------------------------------------------------------- 组装
def build_snapshot(vol_row, chain_row_spx=None, chain_row_basket=None):
    """把 vol_indexes 行 + chain_metrics 行(spx / 篮子汇总)组装成 14 指标快照。"""
    s = {}
    vix = _f(vol_row.get("vix"))
    for k in ("vix", "vvix", "skew", "dspx", "spx", "nvda"):
        s[k] = _f(vol_row.get(k))
    vix9d, vix3m, vixeq = _f(vol_row.get("vix9d")), _f(vol_row.get("vix3m")), _f(vol_row.get("vixeq"))
    if vix9d and vix:
        s["vix9dvix"] = round(vix9d / vix, 4)
    if vix3m and vix:
        s["vixvxv"] = round(vix / vix3m, 4)
    if vixeq and vix:
        s["vixeqVix"] = round(vixeq / vix, 4)
    if chain_row_spx:
        s["spxGex"] = _f(chain_row_spx.get("gex_b"))
        s["dealerGamma"] = s["spxGex"]          # naive 同口径
        s["netDelta"] = _f(chain_row_spx.get("netdelta_proxy"))
        s["pc_idx"] = _f(chain_row_spx.get("pc_vol"))
    if chain_row_basket:
        s["pc_eq"] = _f(chain_row_basket.get("pc_vol"))
        # 综合 P/C 代理:两口径成交量加权
        cv = (_f(chain_row_spx.get("call_vol")) or 0) + (_f(chain_row_basket.get("call_vol")) or 0)
        pv = (_f(chain_row_spx.get("put_vol")) or 0) + (_f(chain_row_basket.get("put_vol")) or 0)
        s["pc_total"] = round(pv / cv, 4) if cv else None
    s["stress"] = compute_stress(s)
    s["regime"] = detect_regime(s)
    s["checklists"] = checklists(s)
    return s
