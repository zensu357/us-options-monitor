"""阈值/权重/符号配置 —— 14 指标与压力指数权重移植自付鹏仪表盘原版。

口径说明见 README:凡标注 proxy 的指标,阈值视为待重校先验。
"""

import pathlib

BASE = pathlib.Path(__file__).resolve().parent.parent
DATA = BASE / "data"
OUT = BASE / "out"
RAW = BASE / "raw"
# 盯盘状态单独放 state/,不进 data/ —— 否则 CI 里 actions/cache 恢复整个
# data/ 会覆盖 git 中的新版本(曾把已删除的脏行复活)。
STATE = BASE / "state"

# 原始期权链 JSON 保留天数(每份 SPX 链约 15MB)
KEEP_RAW_DAYS = 10

# ---------------------------------------------------------------- Yahoo 符号
YAHOO_SYMBOLS = {
    "^VIX": "vix",
    "^VIX9D": "vix9d",
    "^VIX3M": "vix3m",      # 即原版 VXV(2017 年 Cboe 将 VXV 更名 VIX3M)
    "^VVIX": "vvix",
    "^SKEW": "skew",
    "^DSPX": "dspx",
    "^VIXEQ": "vixeq",
    "^GSPC": "spx",
    "NVDA": "nvda",
}

# 个股/ETF 篮子:自算"个股 P/C 代理"(官方全市场口径不可得)
EQ_BASKET = ["SPY", "QQQ", "NVDA", "TSLA", "AAPL", "MSFT", "META", "AMZN", "AVGO", "GOOGL"]

# ---------------------------------------------------------------- 指标阈值
# 每项: (red 条件用的参数, amber 条件用的参数) —— evalStatus 逻辑在 stress.py
THRESHOLDS = {
    # 一、离散与相关性
    "vixeq_amber_low": 2.15,     # v < 1.85 red;v < 2.15 amber
    "vixeq_red_low": 1.85,
    "dspx_red": 35.0,            # dspx<35 且 vix>25 => red;dspx<39 => amber
    "dspx_amber": 39.0,
    "nvda_red": 148.0,
    "nvda_amber": 160.0,
    # 二、波动率与流动性挤兑
    "vix_red": 28.0,             # >28 触发 Vanna
    "vix_amber": 20.0,
    "vvix_red": 115.0,
    "vvix_amber": 100.0,
    # 三、期限结构与偏度
    "term_red": 1.00,            # VIX/VXV、VIX9D/VIX 共用:>1 red,>=0.95 amber
    "term_amber": 0.95,
    "skew_amber_high": 160.0,    # SKEW>=160 amber(尾部拥挤)
    "skew_red_vix_gate": 25.0,   # vix>=25 且 skew<150 => red(见顶回落)
    "skew_red_below": 150.0,
    # 四、期权流量 P/C
    "pc_eq_red": 0.80,
    "pc_eq_amber": 0.68,
    "pc_total_red": 1.25,
    "pc_total_amber": 1.00,
    "pc_idx_red": 1.25,
    "pc_idx_amber": 1.12,
    # 五、做市商敞口
    "gex_red": -50.0,            # $B per 1% move(naive 口径,量级与 SpotGamma 可比)
    "dealer_gamma_red": -5.0,
    "netdelta_red": -40.0,       # 重标定后(原版 -60/150 ≈ -40/100)
}

# regime 状态机参数(原版)
REGIME = {
    "dealer_floor": -8.6,        # Squeezemetrics 口径历史底线,仅作展示参考,不参与判定
    "gex_extreme": -100.0,       # naive 口径的深度负 Gamma 极值(本口径自定,可随历史重校)
    "s3_vix_gate": 26.0,
    "s1_vix": 18.0,
    "s1_gex": 25.0,
    "s1_dealer_gamma": 1.5,
    "s1_skew": 158.0,
    "s4_skew": 155.0,
    "s4_gex": 25.0,
    "s4_vixeq": 2.0,
}

# ---------------------------------------------------------------- 压力指数权重
# 原版满分 100:波动率 25 + 期限 15 + 做市商敞口 30 + 离散 15 + 流量 15
STRESS_SCALE = {
    "vix": 15.0, "vvix": 10.0,
    "vixvxv": 9.0, "vix9dvix": 6.0,
    "gex": 12.0, "dealerGamma": 10.0, "netDelta": 8.0,
    "vixeqVix": 15.0,
    "pc_eq": 6.0, "pc_total": 5.0, "pc_idx": 4.0,
}

# 压力指数各分项归一化区间(原版)
STRESS_RANGE = {
    "vix": (14.0, 36.0), "vvix": (85.0, 135.0),
    "vixvxv": (0.88, 1.12), "vix9dvix": (0.88, 1.12),
    "gex": (-120.0, 20.0),        # 原版: (20-gex)/140 → gex 越负分越高
    "dealerGamma": (-9.0, 1.0),   # (1-dg)/10;naive 口径下与 gex 同源
    "netDelta": (-140.0, 20.0),   # (20-nd)/160,重标定后映射 [-100,20]→线性
    "vixeqVix": (1.35, 2.5),      # (2.5-v)/1.15
    "pc_eq": (0.50, 0.90), "pc_total": (0.80, 1.35), "pc_idx": (1.00, 1.40),
}
