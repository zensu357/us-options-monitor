"""每日 HTML 报告:jinja2 单模板 + CDN 图表,离线时表格仍可读。"""

import datetime
import html as html_mod

from . import config, store, stress

TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>美股期权微观结构监控 · {{ date }}</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
<style>
  body { background:#F8FAFC; color:#0F172A; -webkit-font-smoothing:antialiased; }
  .tabular-nums { font-variant-numeric: tabular-nums; }
  .dot { width:.5rem; height:.5rem; border-radius:9999px; display:inline-block; }
  .dot-red{background:#DC2626}.dot-amber{background:#F59E0B}
  .dot-green{background:#10B981}.dot-na{background:#94A3B8}
</style>
</head>
<body class="min-h-screen font-sans">
<header class="bg-white border-b border-slate-200 sticky top-0 z-30 shadow-sm">
  <div class="max-w-[1280px] mx-auto px-4 sm:px-6 py-3.5 flex flex-wrap items-center justify-between gap-3">
    <div>
      <div class="flex items-center gap-2.5">
        <span class="px-2 py-0.5 rounded text-[11px] font-semibold tracking-wider uppercase bg-slate-900 text-white">US OPTIONS MONITOR</span>
        <h1 class="text-lg font-bold tracking-tight">美股期权微观结构监控 · {{ date }}</h1>
      </div>
      <p class="text-xs text-slate-500 mt-1">免费数据源复刻版 · SPX {{ '%.2f'|format(spx) }} · VIX {{ vix }} · VVIX {{ vvix }} · 数据时点 {{ quote_ts }}</p>
    </div>
    <div class="flex items-center gap-3">
      <div class="bg-slate-50 border border-slate-200 rounded-lg px-3.5 py-2">
        <div class="text-[11px] text-slate-500 font-medium leading-none">综合压力指数</div>
        <div class="flex items-baseline gap-1 mt-1">
          <span class="text-2xl font-bold tabular-nums leading-none {{ stress_cls }}">{{ stress if stress is not none else '--' }}</span>
          <span class="text-xs text-slate-400 font-medium">/ 100</span>
        </div>
      </div>
      <div class="border rounded-lg px-3.5 py-2 {{ regime_box_cls }}">
        <div class="text-[11px] font-medium text-slate-500 leading-none">系统自动判定阶段</div>
        <div class="flex items-center gap-2 mt-1">
          <span class="w-2 h-2 rounded-full {{ regime_dot_cls }}"></span>
          <span class="text-sm font-bold leading-none {{ regime_text_cls }}">{{ regime.title }}</span>
        </div>
      </div>
    </div>
  </div>
</header>

<main class="max-w-[1280px] mx-auto px-4 sm:px-6 py-5 space-y-5">

{% if regime.macroDefense %}
<section class="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm font-semibold text-red-800 flex items-center gap-2">
  <span class="w-1.5 h-1.5 rounded-full bg-red-600 animate-pulse"></span>
  已触发:宏观全面防御升级警报(指数 P/C ≥1.25 + 个股 P/C ≥0.80,或 Dealer Gamma 跌穿参考底线)
</section>{% endif %}

<section class="grid grid-cols-1 lg:grid-cols-3 gap-4">
  <div class="bg-white border border-slate-200 rounded-lg p-4">
    <h3 class="text-sm font-bold">波动率期限结构 <span class="text-[11px] font-medium text-slate-500 ml-1">{{ term_badge }}</span></h3>
    <div class="relative h-48 mt-2"><canvas id="tsChart"></canvas></div>
    <div class="mt-2 pt-2 border-t border-slate-100 grid grid-cols-3 gap-2 text-center text-xs">
      <div><div class="text-slate-400">VIX9D</div><div class="font-bold tabular-nums">{{ vix9d }}</div></div>
      <div><div class="text-slate-400">VIX 30D</div><div class="font-bold tabular-nums">{{ vix }}</div></div>
      <div><div class="text-slate-400">VIX3M(=VXV)</div><div class="font-bold tabular-nums">{{ vix3m }}</div></div>
    </div>
  </div>

  <div class="bg-white border border-slate-200 rounded-lg p-4">
    <h3 class="text-sm font-bold">期权流量 P/C <span class="text-[11px] font-medium text-slate-500 ml-1">proxy 口径</span></h3>
    <div class="relative h-48 mt-2"><canvas id="pcChart"></canvas></div>
    <div class="mt-2 pt-2 border-t border-slate-100 text-[11px] text-slate-500">红线:个股 0.80 / 综合 1.25 / 指数 1.25 · 阈值沿用原版,待 60 日自校</div>
  </div>

  <div class="bg-white border border-slate-200 rounded-lg p-4">
    <h3 class="text-sm font-bold">做市商敞口 <span class="text-[11px] font-medium text-slate-500 ml-1">naive 口径</span></h3>
    <div class="space-y-3 mt-3">
      <div>
        <div class="flex justify-between text-xs"><span class="font-semibold">SPX GEX($B / 1% move)</span>
        <span class="font-bold tabular-nums {{ 'text-red-600' if gex is not none and gex < 0 else 'text-emerald-600' }}">{{ gex if gex is not none else '--' }}</span></div>
        <div class="relative h-4 mt-1 bg-slate-100 border border-slate-200 rounded overflow-hidden">
          <div class="absolute inset-y-0 left-0 w-1/2 bg-red-50/70"></div><div class="absolute inset-y-0 right-0 w-1/2 bg-emerald-50/60"></div>
          <div class="absolute inset-y-0 border-l-2 border-slate-800 z-10" style="left:50%"></div>
          {% if gex is not none %}<div class="absolute inset-y-0.5 rounded-sm {{ 'bg-red-600/85 right-1/2' if gex < 0 else 'bg-emerald-600/85 left-1/2' }}" style="width: {{ gex_pct }}%"></div>{% endif %}
        </div>
      </div>
      <div>
        <div class="flex justify-between text-xs"><span class="font-semibold">Net Delta 代理(±100)</span>
        <span class="font-bold tabular-nums {{ 'text-red-600' if nd is not none and nd < 0 else 'text-emerald-600' }}">{{ nd if nd is not none else '--' }}</span></div>
        <div class="relative h-4 mt-1 bg-slate-100 border border-slate-200 rounded overflow-hidden">
          <div class="absolute inset-y-0 left-0 w-1/2 bg-red-50/70"></div><div class="absolute inset-y-0 right-0 w-1/2 bg-emerald-50/60"></div>
          <div class="absolute inset-y-0 border-l-2 border-slate-800 z-10" style="left:50%"></div>
          {% if nd is not none %}<div class="absolute inset-y-0.5 rounded-sm {{ 'bg-red-600/85 right-1/2' if nd < 0 else 'bg-emerald-600/85 left-1/2' }}" style="width: {{ nd_pct }}%"></div>{% endif %}
        </div>
      </div>
      <div class="text-[11px] text-slate-500">GEX 累计 {{ n_chain_days }} 日,历史极值待自积累后替换他家"-8.6B 底线"。</div>
    </div>
  </div>
</section>

<section class="bg-white border border-slate-200 rounded-lg p-4">
  <h2 class="text-sm font-bold mb-3">五大维度 14 指标状态</h2>
  <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
  {% for gtitle, items in indicator_groups %}
    <div class="border border-slate-200 rounded-lg p-3.5">
      <h3 class="text-xs font-bold tracking-wide mb-2">{{ gtitle }}</h3>
      {% for name, label, thresh, note, status, val in items %}
      <div class="flex items-center justify-between gap-2 py-1.5 {{ 'border-t border-slate-100' if not loop.first }}">
        <div class="min-w-0">
          <div class="text-xs font-semibold flex items-center gap-1.5"><span class="dot dot-{{ status }}"></span>{{ label }}</div>
          <div class="text-[11px] text-slate-400 truncate">{{ thresh }}{% if note %} · {{ note }}{% endif %}</div>
        </div>
        <div class="text-xs font-bold tabular-nums shrink-0">{{ val }}</div>
      </div>
      {% endfor %}
    </div>
  {% endfor %}
  </div>
</section>

<section class="bg-white border border-slate-200 rounded-lg p-4">
  <h2 class="text-sm font-bold mb-3">每日复盘 Checklist</h2>
  <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
    <div class="border border-red-200/80 bg-red-50/20 rounded-lg p-3.5">
      <h3 class="text-xs font-bold text-red-800 uppercase mb-2">风险升级确认项({{ risk_hits }}/4)</h3>
      {% for it in checklists.risk %}
      <div class="flex items-start gap-2 py-1.5 {{ 'border-t border-slate-100' if not loop.first }}">
        <span class="dot mt-1 {{ 'dot-red' if it.triggered else 'dot-na' }}"></span>
        <div><div class="text-xs font-semibold">{{ it.text }}</div>
        <div class="text-[11px] {{ 'text-red-600 font-semibold' if it.triggered else 'text-slate-400' }}">{{ '已触发' if it.triggered else '未触发' }}</div></div>
      </div>
      {% endfor %}
    </div>
    <div class="border border-emerald-200/80 bg-emerald-50/20 rounded-lg p-3.5">
      <h3 class="text-xs font-bold text-emerald-800 uppercase mb-2">止跌与重置确认项({{ reset_hits }}/4)</h3>
      {% for it in checklists.reset %}
      <div class="flex items-start gap-2 py-1.5 {{ 'border-t border-slate-100' if not loop.first }}">
        <span class="dot mt-1 {{ 'dot-green' if it.triggered else 'dot-na' }}"></span>
        <div><div class="text-xs font-semibold">{{ it.text }}</div>
        <div class="text-[11px] {{ 'text-emerald-700 font-semibold' if it.triggered else 'text-slate-400' }}">{{ '条件满足' if it.triggered else '未满足' }}</div></div>
      </div>
      {% endfor %}
    </div>
  </div>
</section>

{% if stress_hist %}
<section class="bg-white border border-slate-200 rounded-lg p-4">
  <h2 class="text-sm font-bold mb-2">压力指数历史(无链数据的日期为"仅波动率"口径,分项自动归一)</h2>
  <div class="relative h-56"><canvas id="stressChart"></canvas></div>
</section>
{% endif %}

<section class="bg-white border border-slate-200 rounded-lg p-4 text-[11px] text-slate-500 leading-relaxed">
  <div class="font-bold text-slate-700 mb-1">口径与免责</div>
  dealer 持仓方向为假设推断;GEX 为 naive 口径(call 正 / put 负),与 SpotGamma 头条同公式、量级可比;P/C 为链自算代理;
  Net Delta 为重标定代理(±100)。阈值全部移植自原仪表盘,视为待拟合先验。仅用于研究复盘,不构成投资建议。
  底层数据:Yahoo chart API + CBOE delayed quotes({{ quote_ts }})。
</section>
</main>

<script>
const tsData = { labels: ['VIX9D','VIX 30D','VIX3M'], values: [{{ vix9d }}, {{ vix }}, {{ vix3m }}] };
const pcData = { labels: ['个股(篮子)','综合','指数(SPX)'], values: [{{ pc_eq if pc_eq is not none else 'null' }}, {{ pc_total if pc_total is not none else 'null' }}, {{ pc_idx if pc_idx is not none else 'null' }}], thresholds: [0.80, 1.25, 1.25] };
{% if stress_hist %}
const stressHist = {{ stress_hist }};
{% endif %}
</script>
<script>
(function render(){
  if (typeof Chart === 'undefined') return; // 离线时表格仍可读
  new Chart(document.getElementById('tsChart'), { type:'line',
    data:{ labels: tsData.labels, datasets:[
      { label:'期限结构', data: tsData.values, borderColor:'#DC2626', backgroundColor:'rgba(220,38,38,.08)', borderWidth:2.5, pointRadius:5, fill:true, tension:.18 },
      { label:'Vanna 阈值 28', data:[28,28,28], borderColor:'#94A3B8', borderWidth:1.5, borderDash:[5,4], pointRadius:0, fill:false }]},
    options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{position:'bottom',labels:{boxWidth:12,font:{size:11}}}} } });
  new Chart(document.getElementById('pcChart'), { type:'bar',
    data:{ labels: pcData.labels, datasets:[
      { label:'当前', data: pcData.values, backgroundColor:['#64748B','#EA580C','#1D4ED8'], borderRadius:4 },
      { label:'红线', data: pcData.thresholds, backgroundColor:'rgba(220,38,38,.16)', borderColor:'#DC2626', borderWidth:1.5, borderDash:[3,3], borderRadius:4 }]},
    options:{ responsive:true, maintainAspectRatio:false, scales:{y:{beginAtZero:true,suggestedMax:1.6}}, plugins:{legend:{position:'bottom',labels:{boxWidth:12,font:{size:11}}}} } });
  {% if stress_hist %}
  const el = document.getElementById('stressChart');
  if (el) new Chart(el, { type:'line',
    data:{ labels: stressHist.map(d=>d[0]), datasets:[
      { label:'压力指数', data: stressHist.map(d=>d[1]), borderColor:'#1E3A8A', borderWidth:2, pointRadius:0, fill:false, tension:.2 }]},
    options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}}, scales:{x:{ticks:{maxTicksLimit:10,font:{size:10}}}} } });
  {% endif %}
})();
</script>
</body>
</html>
"""


def _pct(v, cap):
    if v is None:
        return 0
    return round(min(abs(v) / cap, 1.0) * 50, 1)


def _status_pairs(s):
    rows = []
    for gtitle, items in stress.INDICATOR_GROUPS:
        row = []
        for key, label, thresh, note in items:
            status = stress.eval_indicator(key, s)
            val = s.get(key)
            val_s = "--" if val is None else f"{val:g}"
            row.append((key, label, thresh, note, status, val_s))
        rows.append((gtitle, row))
    return rows


def _stress_history():
    rows = store.read("scores")
    out = []
    for r in rows[-260:]:
        try:
            v = r.get("stress")
            if v not in (None, "", "None"):
                out.append([r["date"], float(v)])
        except (KeyError, ValueError):
            continue
    return out


def render(snapshot, date_str, quote_ts=None):
    regime = snapshot["regime"]
    color_cls = {
        "red": ("bg-red-50 border-red-200", "bg-red-600", "text-red-700"),
        "amber": ("bg-amber-50 border-amber-200", "bg-amber-500", "text-amber-800"),
        "green": ("bg-emerald-50 border-emerald-200", "bg-emerald-600", "text-emerald-800"),
        "blue": ("bg-blue-50 border-blue-200", "bg-blue-700", "text-blue-900"),
    }[regime["color"]]
    s = snapshot
    stress_v = s.get("stress")
    stress_cls = ("text-red-600" if stress_v is not None and stress_v >= 70
                  else "text-amber-600" if stress_v is not None and stress_v >= 40
                  else "text-emerald-600")
    is_back = (s.get("vixvxv") or 0) > 1.0 or (s.get("vix9dvix") or 0) > 1.0
    from jinja2 import Template
    html = Template(TEMPLATE).render(
        date=date_str,
        spx=s.get("spx") or 0,
        vix=s.get("vix") or 0,
        vvix=s.get("vvix") or 0,
        vix9d=s.get("vix9d") or 0,
        vix3m=s.get("vix3m") or 0,
        quote_ts=quote_ts or "-",
        stress=stress_v,
        stress_cls=stress_cls,
        regime=regime,
        regime_box_cls=color_cls[0],
        regime_dot_cls=color_cls[1],
        regime_text_cls=color_cls[2],
        indicator_groups=_status_pairs(s),
        gex=s.get("spxGex"),
        gex_pct=_pct(s.get("spxGex"), 130),
        nd=s.get("netDelta"),
        nd_pct=_pct(s.get("netDelta"), 100),
        pc_eq=s.get("pc_eq"),
        pc_total=s.get("pc_total"),
        pc_idx=s.get("pc_idx"),
        term_badge="Backwardation 倒挂" if is_back else "Contango 升水",
        checklists=s["checklists"],
        risk_hits=sum(1 for it in s["checklists"]["risk"] if it["triggered"]),
        reset_hits=sum(1 for it in s["checklists"]["reset"] if it["triggered"]),
        n_chain_days=len(store.read("chain_metrics")),
        stress_hist=_stress_history(),
    )
    config.OUT.mkdir(parents=True, exist_ok=True)
    path = config.OUT / f"report_{date_str}.html"
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path
