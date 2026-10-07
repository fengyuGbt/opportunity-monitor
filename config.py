"""海外商业机会监控 —— 配置文件
改这里就行，不用动主程序。关键词权重越高，命中时分数越高。
"""
import os

# 关键词打分表：词 -> 权重。文本命中一个词就加一次权重。
# 权重建议：越代表"高价值对口需求"的词权重越高（如 xbrl、financial compliance）。
KEYWORDS = {
    "odoo": 2,
    "erp": 2,
    "xbrl": 3,
    "financial compliance": 3,
    "accounting": 1,
    "middleware": 1,
    "integration": 1,
    "battery": 1,
    "python": 1,
    "freelance": 2,
    "contract": 1,
}

# 只有总分 >= MIN_SCORE 的机会才推送。想多看一点就调成 1，想更精就调成 3。
MIN_SCORE = 2

# 单次最多推送条数
MAX_ITEMS = 12

# 只扫描最近 N 小时内的新内容（配合去重库，窗口大一点不会重复推送）。
# 注意 RemoteOK 职位更新较慢（约每 1-3 天才上新），72h 窗口才能覆盖到。
LOOKBACK_HOURS = 72

# 来源开关：暂时不用的来源改成 False
ENABLE_HN_STORIES = True   # HN 关键词相关热门帖
ENABLE_HN_HIRING = True    # HN "Who is hiring" 月度招聘帖评论
ENABLE_REMOTEOK = True     # RemoteOK 全球远程职位
ENABLE_GITHUB = False      # GitHub Issues：默认关（多为技术讨论噪音，需要时开启并聚焦 GITHUB_QUERY）

# GitHub Issues 搜索查询（若开启 ENABLE_GITHUB，建议聚焦"机会信号"词，如加 freelance / help wanted）
GITHUB_QUERY = 'odoo OR xbrl OR "financial compliance" is:issue'

# ---- GitHub 看板推送 ----
# 每次命中新机会时，发一条评论到仓库的固定 Issue（GitHub App / 邮件会收到通知）
GITHUB_REPO = os.environ.get("GITHUB_REPO", "fengyuGbt/opportunity-monitor")
GITHUB_ISSUE = int(os.environ.get("GITHUB_ISSUE", "1"))  # 固定看板 Issue 编号

# GitHub token 获取：GitHub Actions 自动注入 GITHUB_TOKEN；本地跑从 gh 登录态取。
# 远程 WSL 非登录 shell 的 PATH 可能不含 ~/.local/bin，这里指定 gh 完整路径。
GH_BIN = os.environ.get("GH_BIN", "/home/erp/.local/bin/gh")
