"""微信推送链路测试（一次性）：发一条测试消息到微信。"""
import sys

sys.path.insert(0, "/home/erp/opportunity-monitor")

import config  # noqa: E402  （import config 时自动加载 .env）
from monitor import push_wechat  # noqa: E402

print("SENDKEY 已配置:", bool(config.WECHAT_SENDKEY))
ok = push_wechat(
    "海外机会雷达 · 微信推送测试\n\n链路验证成功 ✅\n\n之后每次命中新的对口机会，报告会自动推送到这里。\n\n—— opportunity-monitor（远程 WSL）",
    1,
)
print("推送结果:", ok)
