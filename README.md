# us-options-monitor — 美股期权微观结构与流动性踩踏监控

复刻付鹏"美股期权微观结构与流动性踩踏监控仪表盘"的框架逻辑，用**免费数据源**自动化落地：
数据采集 → 14 指标 / 压力指数 / 四阶段状态机 / 双向 checklist → 每日 HTML 报告 → 修复信号推送 → 事件研究回测。

> 上游仓库：[zensu357/us-options-monitor](https://github.com/zensu357/us-options-monitor)
> 生产调度：Cloudflare Worker cron（准点）→ GitHub Actions（执行）

---

## 当前状态（2026-11-25 收盘）

| 指标 | 读数 | 说明 |
| --- | --- | --- |
| VIX / VVIX | 28.29 / 115.38 | 自 11-20 的 35.89 / 138.03 回落，但 11-25 又回升 |
| VIX/VIX3M · VIX9D/VIX | 1.0761 · 1.0467 | **仍倒挂**，且较 11-24 走阔 |
| SPX GEX（naive） | **−66.9 $B/1%** | 做市商仍在放大器内 |
| Net Delta 代理 | +62.7 | 转正 |
| 指数 P/C · 篮子 P/C | 0.604 · 0.940 | 恐慌性买跌已退潮 |
| SKEW / DSPX | 142.06 / 43.24 | 尾部保护需求正常化 |
| 综合压力指数 | **60 / 100** | 自 93 回落 |
| 修复信号 / 风险信号 | **0/4 · 1/4** | 未触发修复确认 |

**四条修复信号距离**（触发即邮件告警）：

| 信号 | 当前 | 触发条件 | 还差 |
| --- | --- | --- | --- |
| R1 GEX 重置 | GEX −66.9 / NetDelta +62.7 ✓ | GEX > −30 $B 且 NetDelta ≥ 0 | GEX 37 个点 |
| R2 VVIX 降温 | 115.38 | < 110 | 5.4 |
| R3 倒挂解除 | 1.0761 / 1.0467 | 双双 < 1.00 | **4.7~7.6** |
| R4 离散止血 | VIX 28.29、VIXEQ/VIX 1.824 ✓ | VIX < 25 | 3.3 |

核心结论：**反弹 ≠ 修复**。11-20 暴跌后指数两日收复全部跌幅，但期限结构重新走阔、GEX 仍深度为负、修复信号 0/4 —— "阶段三 → 阶段四"的过渡尚未确认。

---

## 快速开始

```bash
python3 -m usoptmon run            # 全流程：采集 + 评分 + 报告
python3 -m usoptmon collect        # 仅采集（--years 10 拉更长历史，--no-raw 不存原始链）
python3 -m usoptmon score          # 重算 scores.csv 并打印当日摘要
python3 -m usoptmon report         # 重渲染 HTML（--date 指定日期）
python3 -m usoptmon watch          # 修复信号巡检（含 SPX 链，R1~R4 全参评）
python3 -m usoptmon watch --no-chain   # 轻量巡检（只盯 R2/R3/R4，快）
python3 -m usoptmon watch --test   # 无信号翻转也强发一条状态板，用于验证推送通路
python3 -m usoptmon need-eod       # 退出码 0 = 已收盘但当日缺数据，需要补跑全量
python3 -m usoptmon backtest       # 事件研究（Yahoo 10 年日线）
```

依赖：Python 3.10+ 与 numpy / requests / jinja2（**无新增依赖**；刻意不用 pandas/pyarrow，不动既有环境）。

---

## 数据源与口径（重要）

| 数据 | 来源 | 口径说明 |
| --- | --- | --- |
| VIX / VIX9D / VIX3M / VVIX / SKEW / DSPX / VIXEQ / SPX / NVDA | Yahoo chart API（免费、无需鉴权） | `^VIX3M` 即原版 VXV；`^DSPX` 为 Cboe 离散度指数；`^VIXEQ` 历史仅数日，当前值可用、回测不可用 |
| SPX 期权链 greeks / OI / volume | CBOE delayed quotes `_SPX.json` | CBOE 自带 delta/gamma/IV，无需自算 BS。**需完整浏览器头 + Session 复用 cookie** |
| 指数 P/C | SPX 链自算（put vol ÷ call vol） | CBOE 官方日度 P/C CSV 端点已失效，改链自算，与官方全指数口径有偏差 |
| 个股 P/C | Yahoo v7 options API（crumb 配方），10 只龙头近端 6 个到期成交量聚合 | CBOE 的 ACL **只放行指数链**（SPX 200，SPY/个股一律 403），故走 Yahoo |
| GEX（naive Dollar Gamma per 1%） | Σγ·OI·100·S²·0.01，call 正 / put 负 | 与 SpotGamma 头条同公式、量级可比；dealer 真实方向未知 |
| Net Delta 代理 | 100·(Σ\|δ\|·vol_call − Σ\|δ\|·vol_put)/(和) ∈ [−100, +100] | 原版 ±150 为专有黑箱，此处重标定 |

**三条口径纪律**（都是踩坑后加的）：

1. **dealerGamma 与 GEX 同值**。naive 口径下它不可能是 −8.6 $B 那种量级，别拿 Squeezemetrics 的"历史底线"去比——量纲不同会造出永久为真的假警报。深度负 Gamma 的判定改用自口径 `GEX ≤ −100 $B`。
2. **篮子 P/C 需要覆盖率守卫**。10 只里成功少于 6 只时置空，不让残缺样本污染"宏观全面防御"判定。
3. **残缺日线必须过滤**。Yahoo 在盘中/盘前会返回只含部分指数的当日 bar；`_core_ok()` 要求 `vix/vvix/vix9d/vix3m` 齐全才算完整交易日。

所有代理项在报告中标注 `proxy`；阈值全部移植自原仪表盘，视为**待拟合先验**——累计约 60 个交易日后应用本项目自身分位数量标定。

---

## 判定体系

- **14 指标 / 5 维度**：离散与相关性（VIXEQ/VIX、DSPX、NVDA）、波动率（VIX、VVIX）、期限结构与偏度（VIX/VIX3M、VIX9D/VIX、SKEW）、期权流量（三个 P/C）、做市商敞口（GEX、Dealer Gamma、Net Delta）
- **综合压力指数 0–100**：原版权重——做市商敞口 30 / 波动率 25 / 期限结构 15 / 离散 15 / 流量 15；缺数据项按剩余权重归一，不会因缺项而系统性偏低
- **四阶段状态机**：①缩圈与离散稳态 ②拥挤见顶与先遣撤退 ③负反馈翻转与 Vanna 踩踏 ④极端出清与反向 Vanna 修复
- **双向 checklist**：风险升级 4 条（向全市场扩散）+ 止跌重置 4 条（反向 Vanna 修复）

---

## 修复信号盯盘（watch）

盯"止跌与重置确认项"四条 + 复合条件（≥3 条成立 = **修复确认**强告警）。**边缘触发**：信号新出现才告警，持续成立每天只提醒一次，回落记一笔——不刷屏。状态在 `data/alert_state.json`，历史在 `data/alerts.csv`，输出还带"距下次月度 OPEX 天数"（日历减压阀）。

### 推送渠道

渠道用 CLI `--notify` 或环境变量 `USOPTMON_NOTIFY`，webhook 类另配 `USOPTMON_WEBHOOK`：

```bash
python3 -m usoptmon watch --notify feishu --webhook https://open.feishu.cn/open-apis/bot/v2/hook/xxx
python3 -m usoptmon watch --notify bark   --webhook <你的BarkKey>
```

**邮件**（零依赖 smtplib，本地与 Actions 通用），五个环境变量：

| 变量 | 说明 | 示例 |
| --- | --- | --- |
| `USOPTMON_SMTP_HOST` | SMTP 服务器 | `smtp.qq.com` / `smtp.163.com` / `smtp.gmail.com` |
| `USOPTMON_SMTP_PORT` | 465 = SSL（默认）/ 587 = STARTTLS | `465` |
| `USOPTMON_SMTP_USER` | 发件邮箱 | `you@qq.com` |
| `USOPTMON_SMTP_PASS` | **授权码**，不是登录密码；Gmail 用应用专用密码 | — |
| `USOPTMON_MAIL_TO` | 收件人，逗号分隔可多个 | `a@x.com,b@y.com` |

本地自测：`export` 上述变量 + `USOPTMON_NOTIFY=mail` 后跑 `watch --test`。
云端：GitHub 仓库 Secrets 里逐个添加同名变量即可（workflow 已把全部 Secret 映射为环境变量，无需改 yml）。

邮件标题即告警内容，例如 `[期权修复盯盘] 🟢 新触发 R2_VVIX降温`，正文是四条信号状态板 + 风险面 + OPEX 倒计时。

---

## 调度架构

```
Cloudflare cron (:07/:37，13:00–22:30 UTC 内派发)      ← 准点，主调度
        │  workflow_dispatch (body: {"ref":"main"})
        ▼
GitHub Actions: monitor.yml（轻量巡检 + need-eod 补位）
        │  收盘后补齐
        ▼
        全量采集 → 评分 → 报告 → 提交 data/ → 信号翻转发邮件

GitHub 自带 cron（monitor.yml / eod.yml）              ← 仅兜底，跑着也无害
```

### 北京时间运行时刻表

| 北京时间 | 频率 | 内容 |
| --- | --- | --- |
| 21:07、21:37、22:07 … 次日 06:07 | 每 30 分钟 | 轻量巡检（Cloudflare 派发） |
| 收盘后首个巡检 | 一次 | 经 `need-eod` 自动补跑全量并提交 |

按周：周一晚 21:07 起 → 周六早晨结束；周末不派发。

### Cloudflare Worker（主调度）

代码：`infra/cloudflare-worker-cron.js`，已部署为 **usoptmon-cron**
→ <https://usoptmon-cron.3194017853.workers.dev/>（访问该 URL 可自检，返回 `Repo: … | token set: true`）

| 配置 | 值 |
| --- | --- |
| Cron 触发器 | `7,37 * * * *`（UTC 每小时 07/37 分） |
| 时段过滤 | 仅 13:00–22:30 UTC 真正派发，其余直接 skip（省额度） |
| 变量 `GH_REPO` | `zensu357/us-options-monitor` |
| 变量 `GH_TOKEN` | fine-grained PAT，仅该仓库 `Actions: Read and write` |
| 触发对象 | `POST /repos/{repo}/actions/workflows/monitor.yml/dispatches` |

**易错点**：`workflow_dispatch` **不接受工作流未声明的 inputs**，多传会 422。因此 Worker 只发 `{"ref":"main"}`；"全量还是轻量"由触发哪个 workflow 文件决定，而不是靠时间推断。

### GitHub Actions（执行层 / 兜底）

| 文件 | cron（UTC） | 行为 |
| --- | --- | --- |
| `monitor.yml` | `7,37 14-20 * * 1-5` | `watch --no-chain` 轻量巡检 + **need-eod 自愈**（已收盘但缺当日数据则补跑全量并提交） |
| `eod.yml` | `23 21 * * 1-5` | `run` 全量 + `watch`，提交 `data/`、上传报告 artifact |

**为什么拆成两个文件**：GitHub 的 cron 延迟可达数小时，若靠"当前几点"推断该跑全量还是轻量，延迟一跨小时界就会判断错——这个 bug 实际造成过两天收盘任务全部空转。现在"跑什么"由文件决定，与触发时刻彻底解耦。

---

## 运维与已知问题

| 现象 | 原因 | 处置 |
| --- | --- | --- |
| **Cloudflare cron 完全不触发** | **在 Cloudflare 后台部署新版本会清空 cron 触发器**（实测：加完触发器后又部署了两次，触发器被抹掉，Worker 24 小时内 0 次 scheduled 调用） | **每次部署后必须回 Settings → 触发事件 → Cron 触发器重新添加**。用 `wrangler deploy` 可把 `[triggers] crons` 写进配置文件，避免这个坑 |
| GitHub `schedule` 长期不触发 | 新仓库 cron **注册需 8~46 小时**，之后**丢弃率约 99%、延迟 2~7 小时** | 生产调度改走 Cloudflare；GitHub cron 留作兜底（数据按日期 upsert，幂等） |
| 收盘数据缺失一天 | 调度被丢弃且当日无任何巡检 | `need-eod` 会在下一次巡检自动补跑；也可手动 `python3 -m usoptmon run` |
| CSV 列顺序漂移 | 旧版 `store.write` 用"首行键顺序"当表头，不同调用方 dict 顺序不同 → 表头旋转（曾让 `date` 列跑到第 13 列） | 已固定 `date, symbol` 在前、其余字母序 |
| 已删除的脏行复活 | `monitor.yml` 曾缓存整个 `data/`，缓存恢复覆盖了 git 新版本 | 盯盘状态移到 `state/`，只缓存 `state/`；`data/` 只走 git |
| 压力指数偏低 | 当日只有波动率数据、链数据缺失 | 缺项按剩余权重归一，属预期行为；报告会标注 |
| `Repo: undefined` | Worker 变量未绑定 | 在 Worker 设置里补 `GH_REPO` |
| dispatch 返回 422 | 多传了 workflow 未声明的 inputs | 只发 `{"ref":"main"}` |

---

## 安全

- 仓库内**不含任何凭据**。GitHub Secrets 存推送口令；Cloudflare 存 `GH_TOKEN`（Worker secret）。
- `GH_TOKEN` 是 fine-grained PAT，范围限本仓库 `Actions: Read and write`，建议每 90 天轮换：新建 PAT → 更新 Cloudflare 的 `GH_TOKEN` 变量 → 删除旧 PAT。
- 邮件用 SMTP 授权码，**不是登录密码**；一旦在截图/聊天中出现过即应轮换。
- 本地调试时不要把 token 写进仓库目录（`.gitignore` 已排除 `article_*.md`、`raw/`、`out/`、`pipeline.log`）。

---

## 事件研究（backtest）

用 Yahoo 长历史复现原版核心触发条件（P/C 与 GEX 无免费历史，不参与）：

- `s3_vanna`：VIX ≥ 28 且（VIX/VIX3M ≥ 1.0 或 VVIX ≥ 110）
- `s3_confluence`：VIX ≥ 26 且倒挂且 VVIX ≥ 110
- `s4_reset`：VIX/VIX3M < 1.0 且 VVIX < 110 且 VIX < 25，且近 30 日出现过 VIX ≥ 26
- `skew_crowd`：SKEW ≥ 160 且 VIX < 25

输出各触发后 SPX 1 / 5 / 10 / 21 交易日前瞻收益与已实现波动，与无条件基线对照；事件明细落 `data/backtest_events.csv`。

### 首跑结论（2016-11 ~ 2026-11，日线，无显著性检验）

| 事件 | n | 21 日均值 vs 基线 | 21 日胜率 | 21 日已实现波动 |
| --- | --- | --- | --- | --- |
| s3_vanna | 50 | **+4.27% vs +1.13%** | **83% vs 69%** | 28.0% vs 15.2% |
| s3_confluence | 32 | +3.98% vs +1.13% | 80% vs 69% | 32.0% vs 15.2% |
| s4_reset | 88 | +1.04% vs +1.13% | 66% vs 69% | 16.4% vs 15.2% |
| skew_crowd | 28 | **−0.05% vs +1.13%** | 61% vs 69% | 13.2% vs 15.2% |

读法（**勿当交易信号**）：

- 阶段三恐慌出清后中期收益高于基线——"机械砸盘的终点是反弹"，但同期波动翻倍，适合右侧分批而非杠杆抄底；
- 阶段四重置条件满足时超额已消失——修复行情启动在先，等 checklist 全部满足再进场偏晚；
- SKEW 拥挤见顶（低 VIX 高 SKEW）是**负向**信号，与"先遣撤退"叙事一致，值得单独做成排序因子。

---

## 目录结构

```
usoptmon/
  cli.py           命令行入口（run/collect/score/report/watch/need-eod/backtest）
  config.py        符号、阈值、权重、regime 参数
  yahoo.py         波动率指数与 SPX/NVDA 日线
  yahoo_options.py 个股篮子 P/C（crumb 配方）
  cboe.py          SPX 期权链下载与解析
  gex.py           GEX / Net Delta 代理 / P-C 计算
  stress.py        14 指标状态灯 / 压力指数 / regime / checklist
  watch.py         修复信号盯盘、边缘触发、推送
  report.py        jinja2 HTML 报告模板
  backtest.py      事件研究
  net.py / store.py  HTTP 与 CSV 存储
data/    vol_indexes / chain_metrics / scores / backtest_events / alerts / alert_state
raw/     原始期权链 JSON 缓存（保留 KEEP_RAW_DAYS 天）
out/     每日 HTML 报告
infra/   cloudflare-worker-cron.js（准点派发 Worker）
.github/workflows/  monitor.yml（轻量+补位）、eod.yml（全量）
```

---

## 边界

- 独立研究课题：不与 `data-platform/`、`projects/` 共享数据或代码，不触碰 CACHE/lake、stock.db。
- **仅用于研究复盘，不构成投资建议**。dealer 持仓方向为假设推断，所有"机械对冲"叙事均为估计量。
- A 股期权市场做市商自主对冲机制弱、场内规模小，这套 gamma 踩踏叙事**不能直接平移**。
