"""链级衍生指标:naive GEX / Net Delta 代理 / P/C。

GEX(naive Dollar Gamma per 1% move):
    Σ_calls γ·OI·100·S²·0.01 − Σ_puts γ·OI·100·S²·0.01    → $B
与 SpotGamma 头条口径同公式;dealer 实际持仓方向未知,为推断量。

Net Delta 代理(重标定到 ±100):
    dv = |δ|·vol·100·S
    ratio = 100·(Σ_calls dv − Σ_puts dv) / (Σ_calls dv + Σ_puts dv)
负值 = 看跌侧 delta 成交占优 = 机械卖出对冲压力方向。
"""

CONTRACT = 100.0  # 一张合约 100 份


def _safe_div(a, b):
    return a / b if b else 0.0


def chain_metrics(rows, spot):
    """由链行(见 cboe.parse_chain)计算链级指标,单位 $B / 比率。"""
    call_gam = put_gam = 0.0
    call_dv = put_dv = 0.0
    call_vol = put_vol = call_oi = put_oi = 0.0
    for r in rows:
        if r["cp"] == "C":
            call_gam += r["gamma"] * r["oi"]
            call_vol += r["volume"]
            call_oi += r["oi"]
            call_dv += abs(r["delta"]) * r["volume"]
        else:
            put_gam += r["gamma"] * r["oi"]
            put_vol += r["volume"]
            put_oi += r["oi"]
            put_dv += abs(r["delta"]) * r["volume"]
    if spot <= 0:
        spot = 1.0
    unit = CONTRACT * spot * spot * 0.01 / 1e9          # 每单位 γ·OI 的 $B
    gex_b = (call_gam - put_gam) * unit                  # $B per 1% move
    dv_scale = CONTRACT * spot / 1e9                     # |δ|·vol → $B
    netdelta = 100.0 * (call_dv - put_dv) / (call_dv + put_dv) \
        if (call_dv + put_dv) > 0 else 0.0
    return {
        "spot": spot,
        "gex_b": round(gex_b, 2),
        "netdelta_proxy": round(netdelta, 1),
        "delta_call_b": round(call_dv * dv_scale, 2),
        "delta_put_b": round(put_dv * dv_scale, 2),
        "call_vol": call_vol,
        "put_vol": put_vol,
        "call_oi": call_oi,
        "put_oi": put_oi,
        "pc_vol": round(_safe_div(put_vol, call_vol), 4),
        "pc_oi": round(_safe_div(put_oi, call_oi), 4),
    }
