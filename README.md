# 海外机会雷达（opportunity-monitor）

零成本、免 API key 的海外商业机会监控系统：定时扫描 4 个免费机会源，按关键词打分，
把最对口的机会发布到仓库固定 Issue 看板（GitHub App / 邮件自动通知）。跑在远程台式机 WSL（Ubuntu-24.04），可一键迁到 GitHub Actions。

## 数据源（v1）

| 来源 | 抓什么 | 价值 | 默认 |
| --- | --- | --- | --- |
| HN 招聘帖 | 当月 "Who is hiring" 帖全部评论 | 海外远程开发岗最集中的地方 | 开 |
| HN 热门帖 | 关键词相关故事帖 | 行业动态 / 需求信号（含部分噪音） | 开 |
| RemoteOK | 全球远程职位 JSON | 真实远程岗位（可远程交付） | 开 |
| GitHub Issues | 关键词相关 issue | Odoo / XBRL 生态需求信号 | 关（多为技术讨论噪音，需要时开启并聚焦 `GITHUB_QUERY`） |

已实测可用的免费源。Upwork RSS 与 We Work Remotely 被 Cloudflare 拦截（403），已弃用；
RFP 门户（UNGM / 世行 STEP 等）留作 v2（需登录/邮件订阅）。

## 架构

```
GitHub Actions 定时(每6h) / WSL cron
        │
        ▼
sources.py  ──► HN招聘帖 ─┐
                HN热门帖 ──┤ 统一 dict 列表
                RemoteOK ──┼──► monitor.py: 打分(关键词权重) ──► SQLite 去重 ──► GitHub 看板 Issue #1 评论
                GitHubIssues┘   （score >= MIN_SCORE 才推）      （seen.db）
```

## 快速开始（远程台式机 WSL）

```bash
cd /home/erp/opportunity-monitor
python3 -m venv venv
venv/bin/pip install -r requirements.txt

# 先干跑验证（只打印不推送）
venv/bin/python monitor.py --dry-run

# 正式跑：把报告发布到仓库看板 Issue #1 评论区
# 本地跑需要 gh 已登录（gh auth login），token 自动从 gh 登录态获取
venv/bin/python monitor.py
```

**通知机制：** 每次命中新机会，报告以评论形式发到仓库固定 Issue
（`https://github.com/fengyuGbt/opportunity-monitor/issues/1`）。
手机装 GitHub App 并关注该仓库，新评论出现时 App / 邮件会推送通知。

### 本地定时（WSL crontab，不依赖 GitHub）

```bash
crontab -e
# 每 6 小时跑一次，日志留痕
23 */6 * * * cd /home/erp/opportunity-monitor && venv/bin/python monitor.py >> run.log 2>&1
```

## GitHub Actions 部署（推荐）

1. 推送到 GitHub（gh 已就绪）：
   ```bash
   gh repo create opportunity-monitor --public --source /home/erp/opportunity-monitor --push
   ```
2. 无需配置 secret：工作流已声明 `issues: write` 权限，Actions 内置的 GITHUB_TOKEN 会自动把报告发到看板 Issue 评论区。
   （注：GITHUB_TOKEN 是仓库内自动注入的，fork 或迁移到其他仓库时会在原仓库 issue 上失效，届时按需调整 `GITHUB_REPO`。）
3. 手动触发验证：Actions → opportunity-monitor → Run workflow。
   之后每 6 小时自动跑；`seen.db` 通过 Actions cache 跨任务保留，不会重复推送。

## 调配置（只需改 config.py）

- **关键词与权重**：`KEYWORDS`。词越对口权重越高；命中即加分，总分达标才推。
  例：`"xbrl": 3` 表示文本里出现 xbrl 加 3 分。
- **阈值**：`MIN_SCORE` 越高推得越精（默认 2）。
- **来源开关**：`ENABLE_*` 改成 False 即停用对应来源。
- **GitHub 查询**：`GITHUB_QUERY` 独立设置，避免关键词表里的通用词带来噪音。

## 如何加一个新来源（教学）

1. 在 `sources.py` 写一个函数，返回统一 dict 列表（id / title / url / text / date / source）。
   任何能抓到的数据源都行：RSS、公开 JSON、页面爬取（加 try/except 防反爬）。
2. 在 `monitor.py` 的 `collect()` 里注册一行（配置开关 + 函数 + 参数）。
3. 改 `config.py` 加对应 `ENABLE_*` 开关，完事。

去重、打分、推送逻辑全部复用，新来源只需写好"抓取"这一件事。

## 已知限制

- 未登录 GitHub API 搜索限流 10 次/分钟：v1 用一次组合查询规避；量大后可配 `GH_TOKEN`。
- HN Algolia 评论接口单页上限 1000 条，招聘帖评论超量时会漏尾段（够用，后续可加分页）。
- 网络出口：本机/远程直连可用；如换网络被反爬，可在 `HEADERS` 里加 Cookie 或走代理。
