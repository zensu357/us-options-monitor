/**
 * Cloudflare Worker:准点触发 GitHub Actions 的 monitor workflow。
 *
 * 为什么需要它:GitHub 的 schedule 是"尽力而为"——公开仓库高峰期可延迟 30 分钟,
 * 极端情况下整次跳过。Cloudflare Cron Triggers 准点执行,调用 GitHub 的
 * workflow_dispatch API 即可获得可靠的触发源。
 *
 * 部署(3 步,全部在浏览器完成):
 *   1. GitHub → Settings → Developer settings → Personal access tokens →
 *      Fine-grained tokens → 新建:仅授权本仓库,权限 Actions: Read and write
 *   2. Cloudflare Dashboard → Workers & Pages → Create Worker → 粘贴本文件
 *   3. Worker → Settings → Variables and Secrets 添加
 *        GH_TOKEN  (Secret)  = 上一步的 PAT
 *        GH_REPO   (Text)    = zensu357/us-options-monitor
 *      → Triggers → Cron Triggers 添加 "7,37 * * * *"(UTC 每小时 07/37 分)
 *         Worker 内部再按 13:00-22:30 UTC 过滤,只在美股时段真正派发。
 *         22:07 UTC(=17:07 ET)那次会触发 monitor 里的 need-eod 补位,确保收盘数据齐全。
 *
 * 注意:Worker 的 cron 走 UTC 且每小时都会触发,因此"只在美股时段拉数据"
 * 由 monitor workflow 内部逻辑与幂等 upsert 保证——非交易时段跑只会重复
 * 写入同一交易日的数据,无副作用。
 */

const DISPATCH_URL = (repo) =>
  `https://api.github.com/repos/${repo}/actions/workflows/monitor.yml/dispatches`;

// 美股交易时段粗判(UTC):冬令时 14:30-21:00,夏令时 13:30-20:00。
// 用宽松窗口,把边界留给 workflow 内部的交易日判定。
function inUsSession(now) {
  const h = now.getUTCHours();
  const m = now.getUTCMinutes();
  const t = h * 60 + m;
  return t >= 13 * 60 && t <= 22 * 60 + 30; // 13:00 - 22:30 UTC
}

export default {
  async scheduled(event, env, ctx) {
    const now = new Date(event.scheduledTime || Date.now());
    if (!inUsSession(now)) {
      console.log("outside US session, skip", now.toISOString());
      return;
    }
    const res = await fetch(DISPATCH_URL(env.GH_REPO), {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GH_TOKEN}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "usoptmon-cron-worker",
      },
      body: JSON.stringify({ ref: "main" }),
    });
    // 204 = 已受理
    console.log("dispatch", res.status, now.toISOString());
  },

  // 方便手动验证部署是否成功:浏览器访问 Worker 域名
  async fetch(request, env) {
    return new Response(
      "usoptmon cron worker OK. Repo: " + env.GH_REPO +
      " | token set: " + Boolean(env.GH_TOKEN),
      { headers: { "content-type": "text/plain; charset=utf-8" } }
    );
  },
};
