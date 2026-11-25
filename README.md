# us-options-monitor — 美股期权微观结构与流动性踩踏监控

复刻付鹏"美股期权微观结构与流动性踩踏监控仪表盘"的框架逻辑,用**免费数据源**自动化落地:
数据采集 → 14 指标/压力指数/regime 状态机/双向 checklist → 每日 HTML 报告 → 事件研究回测。

## 用法

```bash
cd research/us-options-monitor
python3 -m usoptmon run            # 全流程:采集 + 评分 + 报告
python3 -m usoptmon collect        # 仅采集(--years 10 拉更长历史)
python3 -m usoptmon score          # 重算 scores.csv
python3 -m usoptmon report         # 重渲染 HTML
python3 -m usoptmon backtest       # 事件研究(Yahoo 10 年日线)
```

依赖:Python 3.14 + numpy/requests/jinja2(环境里已有,**无新增依赖**;刻意不用 pandas/pyarrow,不动既有环境)。

注意:Yahoo 对 `range=max` 会静默降级成季度线,故全部历史拉取走 `period1/period2` 分段(`yahoo.fetch_history`)。

## 数据源与口径(重要)

| 数据 | 来源 | 口径说明 |
| --- | --- | --- |
| VIX / VIX9D / VIX3M / VVIX / SKEW / DSPX / VIXEQ / SPX / NVDA | Yahoo chart API(免费,无需鉴权) | 原版指标,`^VIX3M` 等价于仪表盘里的 VXV;`^DSPX` 为 Cboe 离散度指数;`^VIXEQ` 仅近几日有历史,当前值可用、回测不可用 |
| SPX 期权链 greeks/OI/volume | CBOE delayed quotes `_SPX.json`(免费,需浏览器头) | CBOE 自带 delta/gamma/IV,无需自算 BS |
| 指数 P/C | SPX 链自算(put vol / call vol) | CBOE 官方日度 P/C CSV 端点已失效,改用链自算;与官方全指数口径有偏差 |
| 个股 P/C | Yahoo v7 options API(crumb 配方),篮子近端 6 个到期的成交量聚合(SPY/QQQ/NVDA/TSLA/AAPL/MSFT/META/AMZN/AVGO/GOOGL) | 实测 CBOE delayed quotes 的 ACL **只放行指数链**(SPX 200,SPY/QQQ/个股一律 403),故个股链改走 Yahoo;官方 equity P/C 是全市场口径,这里只是龙头篮子代理,阈值沿用原版、标注待重校 |
| GEX(naive Dollar Gamma per 1%) | SPX 链 Σγ·OI·100·S²·0.01,call 为正 / put 为负 | 与 SpotGamma 头条口径同公式,量级可比;但 dealer 真实持仓方向未知,"-8.6B 历史底线"属于 Squeezemetrics 口径,**不可直接套用**,需自积累历史后取自身分位 |
| Net Delta Flow 代理 | 100×(Σ\|δ\|·vol 差)/(和) ∈ [−100,+100] | 原版为 ±150 的专有黑箱,这里重标定为"看跌侧 delta 成交占比",负值=机械卖出对冲压力,阈值已重定标 |

所有代理项在报告里明确标注 `proxy`;阈值全部移植自原仪表盘,视为**待拟合先验**——累计约 60 个交易日后应回看本项目自身序列的分位数重新标定。

## 目录

```
data/   CSV 存储(vol_indexes / chain_metrics / scores / backtest_events / alerts / alert_state)
raw/    原始期权链 JSON 缓存(仅保留最近 KEEP_RAW_DAYS 天)
out/    每日 HTML 报告
.github/workflows/monitor.yml  GitHub Actions 调度(见下)
```

## 修复信号盯盘(watch)

```bash
python3 -m usoptmon watch                 # 全量巡检(含 SPX 链,R1~R4 全参评)
python3 -m usoptmon watch --no-chain      # 轻量巡检(只盯 R2/R3/R4,快)
```

设计:盯"止跌与重置确认项"四条(R1 GEX/NetDelta 重置、R2 VVIX<110、R3 倒挂解除、R4 离散止血)
+ 复合条件(≥3 条成立 = "修复确认"强告警)。**边缘触发**:信号新出现才告警,持续成立每天只提醒
一次,回落记一笔——不刷屏。告警历史落 `data/alerts.csv`,状态在 `data/alert_state.json`。
输出还带"距下次月度 OPEX 天数"(日历减压阀)。

推送(可选;渠道用 CLI `--notify` 或环境变量 `USOPTMON_NOTIFY`,webhook 类另配 `USOPTMON_WEBHOOK`):

```bash
python3 -m usoptmon watch --notify feishu --webhook https://open.feishu.cn/open-apis/bot/v2/hook/xxx
python3 -m usoptmon watch --notify bark   --webhook <你的BarkKey>
```

**邮件渠道**(零依赖 smtplib,本地与 Actions 通用),环境变量五个:

| 变量 | 说明 | 示例 |
| --- | --- | --- |
| `USOPTMON_SMTP_HOST` | SMTP 服务器 | `smtp.qq.com` / `smtp.163.com` / `smtp.gmail.com` |
| `USOPTMON_SMTP_PORT` | 465=SSL(默认)/ 587=STARTTLS | `465` |
| `USOPTMON_SMTP_USER` | 发件邮箱 | `you@qq.com` |
| `USOPTMON_SMTP_PASS` | **授权码**(不是登录密码);Gmail 用应用专用密码 | — |
| `USOPTMON_MAIL_TO` | 收件人,逗号分隔可多个 | `a@x.com,b@y.com` |

本地:`export` 上面五个变量 + `USOPTMON_NOTIFY=mail` 后跑 `python3 -m usoptmon watch --test`
(`--test` = 无信号翻转也强发一条状态板,专用于验证通路)。

GitHub Actions:在本机仓库目录逐条执行(gh 会交互式提示粘贴值,授权码不落聊天记录/历史):

```bash
gh secret set USOPTMON_NOTIFY   --body mail
gh secret set USOPTMON_SMTP_HOST            # 回车后粘贴 smtp.qq.com
gh secret set USOPTMON_SMTP_PORT            # 465
gh secret set USOPTMON_SMTP_USER            # you@qq.com
gh secret set USOPTMON_SMTP_PASS            # 授权码
gh secret set USOPTMON_MAIL_TO              # 收件人(逗号分隔可多个)
```

填完后云端验证一条命令:

```bash
gh workflow run monitor.yml -f mode=full -f test_notify=true
gh run watch --exit-status   # 日志出现"[watch] 邮件已发送 -> …"即通路成功
```

之后定时运行自动生效:信号翻转时标题即告警内容,如 `[期权修复盯盘] 🟢 新触发 R2_VVIX降温`。

## 云端调度:GitHub Actions(推荐)

> **2026-11-25 起生产调度已切到 Cloudflare Worker**(见下节)。
> GitHub 自带的 `schedule` 实测**注册要 8~46 小时、丢弃率约 99%、延迟 2~7 小时**,
> 只能当兜底;真正准点的是 Cloudflare 的 cron。
> 两条 workflow 保留:GitHub 的 cron 即使偶尔跑一次也无害(数据按日期 upsert 幂等)。

公开仓库标准分钟数无限,git 本身当数据库(data/ 提交回仓库),无需自己的机器开机。
`.github/workflows/` 已拆成两个文件:

- **`monitor.yml`** `7,37 14-20 * * 1-5`(UTC):`watch --no-chain` 轻量巡检,
  并带 **need-eod 自愈**——若"美股已收盘但当日缺完整日线"就补跑全量并提交
- **`eod.yml`** `23 21 * * 1-5`(UTC):`run` 全量 + `watch`,提交 data/、传 artifact

拆成两个文件的原因:GitHub 的 cron 延迟可达数小时,若靠"当前几点"推断该跑全量
还是轻量,延迟一跨界就会判断错(这个 bug 实际发生过两天,收盘任务全被当成轻量)。

## Cloudflare Worker 准点触发(生产调度)

`infra/cloudflare-worker-cron.js`,已部署为 **usoptmon-cron**
(`https://usoptmon-cron.3194017853.workers.dev/`,访问该 URL 可自检:
返回 `Repo: ... | token set: true`)。

| 配置 | 值 |
| --- | --- |
| Cron 触发器 | `7,37 * * * *`(UTC 每小时 07/37 分) |
| 时段过滤 | 仅 13:00–22:30 UTC 真正派发(其余直接 skip) |
| 变量 `GH_REPO` | `zensu357/us-options-monitor`(密钥类型) |
| 变量 `GH_TOKEN` | fine-grained PAT,仅该仓库 `Actions: Read and write`,90 天有效 |
| 触发对象 | `POST .../actions/workflows/monitor.yml/dispatches` body `{"ref":"main"}` |

要点:workflow 的 `workflow_dispatch` **不接受多余 inputs**(传 `mode` 会 422),
所以 Worker 只发 `ref`;全量/轻量由选了哪个 workflow 文件决定,而非时间。
22:07 UTC(17:07 ET)那次经 need-eod 补位,保证收盘数据齐全。

启用(本工作区不动 git,由你自己推):

```bash
cd research/us-options-monitor
git init && git add -A && git commit -m "usoptmon initial"
gh repo create us-options-monitor --public --source=. --push   # 或自行 remote add + push
```

注意:
1. **CBOE 链对数据中心 IP 可能被 Cloudflare 拦**(家宽已实测通过,Actions 侧待首跑验证);
   被拦时 R1(GEX/NetDelta)缺席,其余信号照常——管线自动降级,不会崩。
2. GitHub schedule 有 3~30 分钟的尽力而为延迟,盯修复信号完全够用。
3. 以后要推送:仓库 Secret 里加 `USOPTMON_NOTIFY`(feishu/bark/generic)与
   `USOPTMON_WEBHOOK`,workflow 的 watch 步骤无需改动(已支持环境变量)。

备选本地 crontab(机器常开的话,两条就够,双跑无害,upsert 按日期去重):

```cron
20 6 * * 2-6  cd /path/to/research/us-options-monitor && python3 -m usoptmon run && python3 -m usoptmon watch
0 23-4 * * 2-6 cd /path/to/research/us-options-monitor && python3 -m usoptmon watch --no-chain
```

## 事件研究(backtest)

用 Yahoo 长历史复现原版核心触发条件(P/C 与 GEX 无历史,缺省不参与):
- `s3_vanna`:VIX≥28 且(VIX/VIX3M≥1.0 或 VVIX≥110)
- `s3_confluence`:VIX≥26 且倒挂且 VVIX≥110(三重共振)
- `s4_reset`:VIX/VIX3M<1.0 且 VVIX<110 且 VIX<25(且近 30 日内出现过 ≥26 的恐慌)
- `skew_crowd`:SKEW≥160 且 VIX<25(尾部拥挤)

输出各触发后 SPX 1/5/10/21 交易日前瞻收益与已实现波动,与无条件基线对照。

### 2026-11-22 首跑结论(2016-11 ~ 2026-11,日线,样本为事件数、无显著性检验)

| 事件 | n | 触发后 21 日均值 vs 基线 | 触发后 21 日胜率 | 触发后 21 日已实现波动 |
| --- | --- | --- | --- | --- |
| s3_vanna(VIX≥28 且倒挂/VVIX≥110) | 50 | **+4.27% vs +1.13%** | **83% vs 69%** | 28.0% vs 15.2% |
| s3_confluence(VIX≥26 三重共振) | 32 | +3.98% vs +1.13% | 80% vs 69% | 32.0% vs 15.2% |
| s4_reset(倒挂解除+VVIX<110) | 88 | +1.04% vs +1.13% | 66% vs 69% | 16.4% vs 15.2% |
| skew_crowd(SKEW≥160 且 VIX<25) | 28 | **-0.05% vs +1.13%** | 61% vs 69% | 13.2% vs 15.2% |

读法(待更多样本与显著性检验,勿当交易信号):
- 阶段三恐慌出清后中期收益**高于**基线——"机械砸盘的终点是反弹",但同期波动翻倍,适合右侧分批而非杠杆抄底;
- 阶段四重置条件触发时超额已消失——修复行情启动在先,等 checklist 满足再进场偏晚;
- SKEW 拥挤见顶(低 VIX 高 SKEW)是**负向**信号——与"先遣撤退"叙事一致,值得后续单独做成排序因子。

## 边界

- 本目录是独立研究课题,不与 data-platform/、projects/ 共享数据或代码,不触碰 CACHE/lake、stock.db。
- 仅用于研究复盘,不构成投资建议;dealer 持仓方向为假设推断,所有"机械对冲"叙事均为估计量。
