"""各机会来源的抓取函数。

统一约定：每个函数返回 list[dict]，字段：
    id     去重用的唯一 ID（str）
    title  标题（含来源/公司前缀更易读）
    url    原文链接
    text   用于关键词打分的全文/摘要（str）
    date   发布时间（epoch 秒，int）
    source 来源名（展示用，str）

新增来源 = 新增一个这样的函数，然后在 monitor.py 的 collect() 里注册一行。
"""
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime

import requests

import config

HEADERS = {"User-Agent": "Mozilla/5.0 (opportunity-monitor)"}

HN_API = "https://hn.algolia.com/api/v1"


def _iso_to_ts(iso):
    """ISO 时间字符串 -> epoch 秒；解析失败返回 0。"""
    if not iso:
        return 0
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0


def fetch_hn_stories(keywords, since_ts):
    """HN：按关键词搜最近的故事帖。每个关键词一次查询。"""
    out, seen = [], set()
    for kw in keywords:
        resp = requests.get(
            f"{HN_API}/search_by_date",
            params={"query": kw, "tags": "story", "hitsPerPage": 30},
            timeout=25,
        )
        resp.raise_for_status()
        for h in resp.json().get("hits", []):
            oid = h.get("objectID")
            if not oid or oid in seen:
                continue
            ts = h.get("created_at_i", 0)
            if ts < since_ts:
                continue
            seen.add(oid)
            title = h.get("title") or ""
            text = (h.get("story_text") or "")[:500]
            out.append({
                "id": f"hn-{oid}",
                "title": title,
                "url": h.get("url") or f"https://news.ycombinator.com/item?id={oid}",
                "text": f"{title}\n{text}",
                "date": ts,
                "source": "HN",
            })
    return out


def fetch_hn_hiring(since_ts):
    """HN：抓最新一期 "Who is hiring" 招聘帖的评论（海外远程开发岗最集中）。
    两跳：先搜到当期招聘帖的 story id，再按 story id 拉评论。
    """
    # 关键：用 search_by_date（按日期排序）找最新一期，用 search（相关度排序）会返回老帖
    resp = requests.get(
        f"{HN_API}/search_by_date",
        params={"query": "Who is hiring", "tags": "story", "hitsPerPage": 20},
        timeout=25,
    )
    resp.raise_for_status()

    story = None
    for h in resp.json().get("hits", []):
        title = h.get("title") or ""
        # 只认正规招聘帖："Ask HN: Who is hiring? (2026-10)" 格式，且是近 45 天内的。
        # 注意要用 startswith 排除 "Show HN: Rank every HN Who is hiring post..." 这类仿冒标题
        if title.startswith("Ask HN: Who is hiring") and h.get("created_at_i", 0) >= since_ts - 45 * 86400:
            story = h  # search_by_date 已按时间倒序，第一个匹配即最新
            break
    if story is None:
        return []

    resp = requests.get(
        f"{HN_API}/search_by_date",
        params={"tags": f"comment,story_{story['objectID']}", "hitsPerPage": 1000},
        timeout=30,
    )
    resp.raise_for_status()

    out = []
    for c in resp.json().get("hits", []):
        ts = c.get("created_at_i", 0)
        if ts < since_ts:
            continue
        text = (c.get("comment_text") or "")[:800]
        out.append({
            "id": f"hnh-{c['objectID']}",
            "title": f"[HN招聘] {story['title']} · {c.get('author', '')}",
            "url": f"https://news.ycombinator.com/item?id={c['objectID']}",
            "text": text,
            "date": ts,
            "source": "HN-Job",
        })
    return out


def fetch_remoteok(since_ts):
    """RemoteOK：全量远程职位 JSON，本地按时间过滤。"""
    resp = requests.get("https://remoteok.com/api", headers=HEADERS, timeout=30)
    resp.raise_for_status()
    jobs = resp.json()
    out = []
    for j in jobs:
        if not isinstance(j, dict) or "id" not in j or "epoch" not in j:
            continue  # 跳过第一条平台公告
        ts = int(j["epoch"])
        if ts < since_ts:
            continue
        pos = j.get("position") or ""
        comp = j.get("company") or ""
        tags = " ".join(j.get("tags") or [])
        desc = (j.get("description") or "")[:500]
        out.append({
            "id": f"ro-{j['id']}",
            "title": f"[{comp}] {pos}",
            "url": j.get("url") or "",
            "text": f"{pos} {comp} {tags}\n{desc}",
            "date": ts,
            "source": "RemoteOK",
        })
    return out


def fetch_reddit(since_ts):
    """Reddit：抓指定 subreddit 的接单/需求帖（Atom RSS，免登录、无需 API key）。
    主要价值：r/forhire 每天 ~30 条新帖，[Hiring] 帖 = 直接的需求方。
    Reddit 国内不可直连，默认走 WSL 内的台式机 Clash 代理。
    """
    out = []
    for sub in config.REDDIT_SUBREDDITS:
        try:
            resp = requests.get(
                f"https://www.reddit.com/r/{sub}/new/.rss?limit=50",
                headers=HEADERS,
                proxies={"http": config.REDDIT_PROXY, "https": config.REDDIT_PROXY},
                timeout=30,
            )
            resp.raise_for_status()
        except Exception as e:  # noqa: BLE001 —— 单个 subreddit 失败不影响其他源
            print(f"[warn] Reddit r/{sub} 抓取失败: {e}")
            continue

        root = ET.fromstring(resp.text)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("a:entry", ns):
            rid = (entry.findtext("a:id", "", ns) or "").strip()
            if not rid:
                continue
            ts = _iso_to_ts(entry.findtext("a:updated", "", ns) or "")
            if ts < since_ts:
                continue
            title = (entry.findtext("a:title", "", ns) or "").strip()
            # 只留 [Hiring]（需求方找人=机会）；跳过 [For Hire]（求职者自我推销=噪音/竞争对手）
            if "for hire" in title.lower():
                continue
            link = ""
            for ln in entry.findall("a:link", ns):
                if ln.get("rel", "alternate") == "alternate":
                    link = ln.get("href", "") or ""
                    break
            raw = entry.findtext("a:content", "", ns) or ""
            body = re.sub(r"<[^>]+>", " ", raw)          # 去 HTML 标签
            body = " ".join(body.split())[:600]           # 折叠空白
            out.append({
                "id": f"rd-{rid}",
                "title": f"[Reddit/{sub}] {title}",
                "url": link,
                "text": f"{title}\n{body}",
                "date": ts,
                "source": "Reddit",
            })
    return out


def fetch_github(since_ts):
    """GitHub Issues：搜索需求信号（如 Odoo 生态里有人求助/找实施）。
    一次组合查询，避免触发未认证限流（search 端点 10 次/分钟）。
    """
    resp = requests.get(
        "https://api.github.com/search/issues",
        params={"q": config.GITHUB_QUERY, "sort": "updated", "order": "desc", "per_page": 50},
        headers={"User-Agent": "opportunity-monitor", "Accept": "application/vnd.github+json"},
        timeout=25,
    )
    if resp.status_code == 403:
        print("[warn] GitHub API 限流，本来源跳过")
        return []
    resp.raise_for_status()

    out = []
    for it in resp.json().get("items", []):
        ts = _iso_to_ts(it.get("created_at"))
        if ts < since_ts:
            continue
        repo = (it.get("repository_url") or "").rsplit("/", 1)[-1]
        title = it.get("title") or ""
        body = (it.get("body") or "")[:400]
        out.append({
            "id": f"gh-{it['id']}",
            "title": f"[{repo}] {title}",
            "url": it.get("html_url") or "",
            "text": f"{title}\n{body}",
            "date": ts,
            "source": "GitHub",
        })
    return out
