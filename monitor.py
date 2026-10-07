#!/usr/bin/env python3
"""海外商业机会最小监控系统 v1
抓取多个免费来源 → 关键词打分 → SQLite 去重 → 推送飞书。

用法：
    python monitor.py            # 正常运行（抓取 + 打分 + 推送）
    python monitor.py --dry-run  # 只打印结果不推送，建议先跑这个验证
"""
import argparse
import sqlite3
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


def push_telegram(text):
    """推送消息到 Telegram（可走代理）。"""
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID):
        print("[error] 未配置 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID（环境变量或 config.py）")
        sys.exit(1)
    proxies = None
    if config.TELEGRAM_PROXY:
        proxies = {"http": config.TELEGRAM_PROXY, "https": config.TELEGRAM_PROXY}
    # Telegram 单条消息上限 4096 字符，截断保底
    payload = text[:3800]
    resp = requests.post(
        f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": config.TELEGRAM_CHAT_ID, "text": payload, "disable_web_page_preview": False},
        proxies=proxies,
        timeout=20,
    )
    resp.raise_for_status()
    print("[info] Telegram 推送成功")


def main():
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
        push_telegram(report)
        for it in fresh:
            mark_seen(conn, it["id"])
        conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
