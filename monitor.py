#!/usr/bin/env python3
"""海外商业机会最小监控系统 v1
抓取多个免费来源 → 关键词打分 → SQLite 去重 → 推送飞书。

用法：
    python monitor.py            # 正常运行（抓取 + 打分 + 推送）
    python monitor.py --dry-run  # 只打印结果不推送，建议先跑这个验证
"""
import argparse
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime

import requests

import config
import sources

DB_PATH = "seen.db"


def load_db():
    """SQLite 去重库：记住已推送过的条目 ID。"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS seen (item_id TEXT PRIMARY KEY)")
    return conn


def is_seen(conn, item_id):
    return conn.execute("SELECT 1 FROM seen WHERE item_id=?", (item_id,)).fetchone() is not None


def mark_seen(conn, item_id):
    conn.execute("INSERT OR IGNORE INTO seen (item_id) VALUES (?)", (item_id,))


def score_text(text, keywords):
    """关键词打分：命中一个词加一次权重。返回 (总分, 命中的词列表)。"""
    t = text.lower()
    total, matched = 0, []
    for kw, w in keywords.items():
        if kw.lower() in t:
            total += w
            matched.append(kw)
    return total, matched


def collect(since_ts, keywords):
    """汇总所有来源的新条目。单个来源失败只告警，不影响其他来源。"""
    items = []
    fetchers = [
        ("ENABLE_HN_STORIES", sources.fetch_hn_stories, (keywords, since_ts)),
        ("ENABLE_HN_HIRING", sources.fetch_hn_hiring, (since_ts,)),
        ("ENABLE_REMOTEOK", sources.fetch_remoteok, (since_ts,)),
        ("ENABLE_GITHUB", sources.fetch_github, (since_ts,)),
    ]
    for flag, fn, args in fetchers:
        if not getattr(config, flag, False):
            continue
        try:
            got = fn(*args)
            print(f"[info] {fn.__name__}: {len(got)} 条")
            items.extend(got)
        except Exception as e:  # noqa: BLE001 —— 来源抓取失败不中断整体
            print(f"[warn] {fn.__name__} 失败: {e}")
    return items


def format_report(fresh, now_str):
    lines = [
        f"海外机会雷达 · {now_str} · 命中 {len(fresh)} 条",
        "（分数 = 关键词权重之和，越高越对口）",
        "",
    ]
    for it in fresh:
        lines.append(f"· [{it['source']} {it['score']}分] {it['title']}")
        lines.append(f"  {it['url']}")
    return "\n".join(lines)


def load_dotenv():
    """读取同目录 .env（本地密钥，不入 git），变量仅在该进程内生效。"""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())


def push_wechat(text, hit_count):
    """推送微信（Server酱 Turbo）。title 简短，desp 支持 Markdown。"""
    resp = requests.post(
        f"https://sctapi.ftqq.com/{config.WECHAT_SENDKEY}.send",
        data={"title": f"海外机会雷达 · 命中 {hit_count} 条", "desp": text},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        print(f"[warn] 微信推送返回异常: {data.get('message')}")
        return False
    print("[info] 微信推送成功")
    return True


def get_github_token():
    """GitHub API token：优先环境变量（Actions 自动注入 GITHUB_TOKEN），本地跑从 gh 登录态取。"""
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    try:
        out = subprocess.run([config.GH_BIN, "auth", "token"], capture_output=True, text=True, timeout=15)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


def push_github(text):
    """把报告发到仓库固定 Issue 的评论区（新评论触发 GitHub App / 邮件通知）。"""
    token = get_github_token()
    if not token:
        print("[error] 未找到 GitHub token：GitHub Actions 会自动注入；本地跑请先 gh auth login")
        sys.exit(1)
    resp = requests.post(
        f"https://api.github.com/repos/{config.GITHUB_REPO}/issues/{config.GITHUB_ISSUE}/comments",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "opportunity-monitor",
        },
        json={"body": text[:65000]},  # 单条评论上限 65536 字符，截断保底
        timeout=20,
    )
    resp.raise_for_status()
    print("[info] GitHub 看板评论发布成功")


def main():
    load_dotenv()
    ap = argparse.ArgumentParser(description="海外商业机会监控")
    ap.add_argument("--dry-run", action="store_true", help="只打印结果，不推送")
    args = ap.parse_args()

    since_ts = int(time.time()) - config.LOOKBACK_HOURS * 3600
    print(f"[info] 扫描最近 {config.LOOKBACK_HOURS} 小时（自 {datetime.fromtimestamp(since_ts):%m-%d %H:%M} 起）")

    items = collect(since_ts, list(config.KEYWORDS))
    print(f"[info] 共抓取 {len(items)} 条")

    conn = load_db()
    fresh = []
    for it in items:
        if is_seen(conn, it["id"]):
            continue
        s, matched = score_text(it["text"], config.KEYWORDS)
        if s >= config.MIN_SCORE:
            it["score"] = s
            it["matched"] = matched
            fresh.append(it)
    fresh.sort(key=lambda x: (-x["score"], -x["date"]))
    fresh = fresh[: config.MAX_ITEMS]
    print(f"[info] 关键词命中 {len(fresh)} 条（阈值 {config.MIN_SCORE} 分）")

    if not fresh:
        print("[info] 本次没有新的对口机会")
        return

    report = format_report(fresh, datetime.now().strftime("%m-%d %H:%M"))
    if args.dry_run:
        print("\n" + report)
    else:
        # 微信 = 即时通知（可选）；GitHub 看板 = 归档（必发）
        if config.WECHAT_SENDKEY:
            try:
                push_wechat(report, len(fresh))
            except Exception as e:  # noqa: BLE001 —— 微信失败不阻断归档
                print(f"[warn] 微信推送失败: {e}")
        push_github(report)
        for it in fresh:
            mark_seen(conn, it["id"])
        conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
