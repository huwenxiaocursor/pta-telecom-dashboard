#!/usr/bin/env python3
"""
每日电信新闻图片邮件
- 截取本地 index.html 当天新闻区域（2× 高清）
- 通过 macOS Apple Mail 生成邮件草稿（收件人放在密送栏），不自动发送——
  由用户在 Mail 的"草稿箱"里人工确认后手动发送
"""

import datetime
import json
import pathlib
import subprocess
import sys
import tempfile

BASE_DIR      = pathlib.Path(__file__).resolve().parent
CACHE_FILE    = BASE_DIR / "news_cache.json"
INDEX_FILE    = BASE_DIR.parent / "index.html"
DASHBOARD_URL = "https://huwenxiaocursor.github.io/pta-telecom-dashboard/"

# 当天无新增新闻（只能回退到旧日期）时，不生成日报草稿，改为只给本人发一封
# 提醒邮件（收件人栏，不密送 18 人），提示今日无新增、已跳过。
NOTIFY_EMAIL = "huwenxiao@zong.com.pk"

# 密送收件人名单（草稿只填密送栏，不填"收件人"栏）
BCC_EMAILS = [
    "huojunli@zong.com.pk",
    "wangyong@zong.com.pk",
    "huangzhidong@zong.com.pk",
    "maoweiliang@zong.com.pk",
    "wujianhe@zong.com.pk",
    "lengxing@zong.com.pk",
    "fanjing@zong.com.pk",
    "zhanglei@zong.com.pk",
    "jiangjisuo@zong.com.pk",
    "fanjiehuan@zong.com.pk",
    "lixiaowei@zong.com.pk",
    "jingxiuming@zong.com.pk",
    "yangchao@zong.com.pk",
    "yanmingqiang@zong.com.pk",
    "zhaofeilong@zong.com.pk",
    "luweidong@zong.com.pk",
    "huwenxiao@zong.com.pk",
    "weilin@zong.com.pk",
]

SOURCE_COLORS = {
    "PTA":              "#1c63d4",
    "SBP":              "#01652e",
    "ProPakistani":     "#ef7a15",
    "Dawn":             "#b91c1c",
    "BusinessRecorder": "#7c3aed",
    "TechJuice":        "#0ea5e9",
}

MAX_DIGEST_ITEMS = 6

# 手机品牌、促销套餐等非政策类内容，在邮件摘要中排除
_DIGEST_EXCLUDE = {
    # 手机品牌
    "tecno", "samsung", "huawei", "iphone", "realme", "xiaomi", "oppo",
    "vivo", "nokia", "motorola", "infinix", "itel", "oneplus", "google pixel",
    # 促销/套餐/产品发布
    "roaming offer", "roaming package", "ziyarat", "hajj package",
    "data offer", "data bundle", "call package", "sms package",
    "discount", "lucky draw", "prize", "cashback", "scratch card",
    "introduces", "launches new", "new package", "new offer", "new bundle",
    # 功能/评测文章
    "how to", "review:", "top 5", "top 10", "best phones", "price in pakistan",
    "specifications", "specs and price",
}


def is_digest_relevant(title: str) -> bool:
    t = title.lower()
    return not any(kw in t for kw in _DIGEST_EXCLUDE)


def load_today_news(date_str: str) -> list:
    """Reads the already-ranked NEWS_DATA that update_news.py injected into
    index.html — this is the exact same PTA-priority/importance/source-priority
    sorted, cross-source-deduped, source-diversity-enforced list the webpage
    shows for that day. The digest must never recompute its own independent
    ranking here: an earlier version did, and it silently drifted out of sync
    with update_news.py's rules (e.g. still had "PhoneWorld" in its priority
    map after it was replaced by "BusinessRecorder", so BusinessRecorder items
    always sorted last and fell off the MAX_DIGEST_ITEMS cutoff). Reading the
    pre-computed list keeps the two permanently in sync by construction."""
    import re
    html = INDEX_FILE.read_text(encoding="utf-8")
    s = html.find("// ===AUTO-NEWS-START===")
    e = html.find("// ===AUTO-NEWS-END===")
    m = re.search(r"const NEWS_DATA = (\[.*\]);", html[s:e], re.S) if s != -1 and e != -1 else None
    all_items = json.loads(m.group(1)) if m else []
    items = [i for i in all_items
             if i.get("date") == date_str
             and i.get("summary_zh", "").strip()
             and is_digest_relevant(i.get("title", ""))]
    return items[:MAX_DIGEST_ITEMS]


def highlight(text: str) -> str:
    import re
    return re.sub(r"【([^】]+)】", r"<strong>\1</strong>", text)


def build_digest_html(items: list, date_str: str) -> str:
    dt           = datetime.date.fromisoformat(date_str)
    date_cn      = f"{dt.year}年{dt.month}月{dt.day}日"
    date_weekday = ["周一","周二","周三","周四","周五","周六","周日"][dt.weekday()]

    cards = ""
    for item in items:
        color = SOURCE_COLORS.get(item["source"], "#6b7280")
        paras = [p.strip() for p in item.get("summary_zh", "").split("\n\n") if p.strip()]
        summary_html = "".join(f"<p>{highlight(p)}</p>" for p in paras)
        cards += f"""
        <div class="card" style="border-left-color:{color};--src-color:{color}">
          <span class="tag" style="background:{color}">{item["source"]}</span>
          <div class="title">{item["title"]}</div>
          <div class="summary">{summary_html}</div>
        </div>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{
  width:960px;background:#f1f5f9;
  font-family:-apple-system,"PingFang SC","Helvetica Neue",sans-serif;
}}
.header{{
  background:linear-gradient(135deg,#1c3d6e 0%,#1c63d4 100%);
  padding:22px 32px 18px;display:flex;align-items:center;justify-content:space-between;
}}
.h-left h1{{color:#fff;font-size:21px;font-weight:700;letter-spacing:.4px}}
.h-right{{text-align:right;color:#bfdbfe;font-size:13px;line-height:1.6}}
.h-right .badge{{
  display:inline-block;background:rgba(255,255,255,.15);
  border-radius:20px;padding:2px 12px;font-size:11px;color:#e0f2fe;margin-top:4px;
}}
.body{{padding:14px 20px 6px}}
.card{{
  background:#fff;border-radius:8px;margin-bottom:12px;
  padding:15px 18px;border-left:4px solid #ccc;
  box-shadow:0 1px 3px rgba(0,0,0,.06);
}}
.tag{{
  display:inline-block;padding:2px 10px;border-radius:20px;
  font-size:11px;font-weight:700;color:#fff;margin-bottom:8px;
}}
.title{{font-size:13.5px;font-weight:600;color:#1e293b;line-height:1.45;margin-bottom:9px}}
.summary{{font-size:12.5px;color:#475569;line-height:1.75}}
.summary p{{margin-bottom:5px}}
.summary p:last-child{{margin-bottom:0}}
.summary strong{{font-weight:700;color:var(--src-color,#1c63d4)}}
.footer{{background:#1e293b;padding:12px 32px;text-align:center}}
.footer-left{{color:#94a3b8;font-size:11px}}
</style>
</head><body>
<div class="header">
  <div class="h-left">
    <h1>Pakistan Telecom &amp; Economy Daily Digest</h1>
  </div>
  <div class="h-right">
    {date_cn} &nbsp;{date_weekday}<br>
    <span class="badge">{len(items)} articles today</span>
  </div>
</div>
<div class="body">{cards}</div>
<div class="footer">
  <span class="footer-left">数据来源：PTA · ProPakistani · SBP · Dawn · Business Recorder · TechJuice &nbsp;|&nbsp; 每日自动更新</span>
</div>
</body></html>"""


def html_to_png(html: str, out_path: str) -> None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": 960, "height": 600},
            device_scale_factor=3,
        )
        page.set_content(html, wait_until="domcontentloaded")
        # 量 footer 底部坐标作为真实内容高度，避免底部留白
        content_height = page.evaluate(
            "Math.ceil(document.querySelector('.footer').getBoundingClientRect().bottom)"
        )
        page.set_viewport_size({"width": 960, "height": content_height})
        page.screenshot(path=out_path, full_page=False)
        browser.close()
    print(f"  图片已生成：{out_path}")


def save_draft_via_apple_mail(img_path: str, subject: str, body: str) -> None:
    """Creates the message with all recipients in Bcc and saves it to Drafts —
    deliberately does NOT call `send`. The user reviews and sends manually.

    Must be created with visible:true. With visible:false, Mail never
    instantiates a real compose window/WebView, so the inserted image
    attachment isn't embedded into the message's real content the same way —
    it shows fine in the read-only Drafts preview pane (which renders from a
    different code path) but disappears when the draft is reopened for
    editing (double-click), because that path relies on the compose view's
    persisted state. This was a real observed bug (2026-07-04)."""
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    lines = [
        'tell application "Mail"',
        f'set msg to make new outgoing message with properties {{subject:"{esc(subject)}", content:"{esc(body)}", visible:true}}',
        "tell msg",
    ]
    for addr in BCC_EMAILS:
        lines.append(f'make new bcc recipient with properties {{address:"{esc(addr)}"}}')
    lines += [
        f'make new attachment with properties {{file name:POSIX file "{img_path}"}} at after the last paragraph',
        "delay 3",
        "end tell",
        "save msg",
        "end tell",
    ]
    args = ["osascript"]
    for line in lines:
        args += ["-e", line]

    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  AppleScript 错误：{result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    print(f"  邮件草稿已保存到 Mail 的草稿箱，密送 {len(BCC_EMAILS)} 人，待手动确认发送")


def save_notice_via_apple_mail(subject: str, body: str) -> None:
    """当天无新增新闻时，只给本人（NOTIFY_EMAIL，收件人栏）生成一封纯文字提醒
    草稿，不密送 18 人、不带附图。同样只 save 到草稿箱，不 send。"""
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    lines = [
        'tell application "Mail"',
        f'set msg to make new outgoing message with properties {{subject:"{esc(subject)}", content:"{esc(body)}", visible:true}}',
        "tell msg",
        f'make new to recipient with properties {{address:"{esc(NOTIFY_EMAIL)}"}}',
        "end tell",
        "save msg",
        "end tell",
    ]
    args = ["osascript"]
    for line in lines:
        args += ["-e", line]

    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  AppleScript 错误：{result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    print(f"  提醒邮件草稿已保存到草稿箱（仅收件人 {NOTIFY_EMAIL}），待手动确认发送")


def main() -> None:
    date_str = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    dt       = datetime.date.fromisoformat(date_str)
    date_cn  = f"{dt.year}年{dt.month}月{dt.day}日"

    print(f"[digest] 日期（T-1）：{date_str}")
    items = load_today_news(date_str)

    if not items:
        # T-1 无新增新闻。以前会自动回退到最近一天有数据的日期，把旧新闻当日报再发
        # 一遍——用户明确要求：这种情况不再生成日报草稿，改为只给本人发一封提醒邮件。
        with open(CACHE_FILE, encoding="utf-8") as f:
            cache = json.load(f)
        latest = max((i["date"] for i in cache if i.get("summary_zh", "").strip()),
                     default=None)
        latest_cn = ""
        if latest:
            ldt = datetime.date.fromisoformat(latest)
            latest_cn = f"{ldt.year}年{ldt.month}月{ldt.day}日"

        print(f"  {date_str} 无新增新闻，跳过日报，生成提醒邮件"
              + (f"（最近有数据：{latest}）" if latest else "（缓存内也无任何可用新闻）"))
        subject = f"巴基斯坦电信资讯日报｜{date_cn} 无新增新闻，已跳过"
        body = (f"您好，\n\n"
                f"{date_cn} 未抓取到符合条件的巴基斯坦电信/宏观新闻，"
                f"今日不生成日报草稿。\n\n"
                + (f"最近一次有新闻的日期为 {latest_cn}（已在此前发送，不再重复）。\n\n"
                   if latest else "新闻缓存内暂无任何可用新闻，请检查抓取任务。\n\n")
                + f"如需人工核对，可在线查看：\n{DASHBOARD_URL}")
        save_notice_via_apple_mail(subject, body)
        print("  完成。")
        return

    print(f"  共 {len(items)} 条新闻，生成图片中…")

    html     = build_digest_html(items, date_str)
    img_path = f"/tmp/telecom_digest_{date_str}.png"
    html_to_png(html, img_path)

    subject = f"巴基斯坦电信资讯日报 {date_cn}（{len(items)} 条）"
    body    = (f"您好，\n\n"
               f"巴基斯坦通信行业资讯（{date_cn}）共 {len(items)} 条，详见附图。\n\n"
               f"在线查看完整版：\n"
               f"{DASHBOARD_URL}")

    print(f"  生成邮件草稿：{subject}")
    save_draft_via_apple_mail(img_path, subject, body)
    print("  完成。")


if __name__ == "__main__":
    main()
