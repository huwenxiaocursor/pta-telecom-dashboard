#!/usr/bin/env python3
"""
Fetches latest Pakistan telecom/economy news from 5 sources,
generates Chinese summaries via DeepSeek, and injects NEWS_DATA into index.html.

Sources: PTA, SBP, PBS, ProPakistani (RSS), PhoneWorld
"""

import datetime
import html as html_lib
import json
import os
import pathlib
import re
import time
import urllib.request
import xml.etree.ElementTree as ET

BASE_DIR   = pathlib.Path(__file__).resolve().parent
CACHE_FILE = BASE_DIR / "news_cache.json"
INDEX_FILE = BASE_DIR.parent / "index.html"
LOG_FILE   = BASE_DIR / "news_update_log.txt"

NEWS_START = "// ===AUTO-NEWS-START==="
NEWS_END   = "// ===AUTO-NEWS-END==="

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

MAX_ITEMS_PER_SOURCE = 20
MAX_DISPLAY_ITEMS    = 400
MAX_PER_DAY          = 5
MAX_DISPLAY_ITEMS    = 400
CUTOFF_DATE          = "2026-01-01"

# Source priority for per-day display ranking (lower = higher priority)
SOURCE_PRIORITY = {"PTA": 0, "ProPakistani": 1, "SBP": 2, "PhoneWorld": 3, "TechJuice": 4}

# Importance ranking for per-day display (lower = shown first); see summarize()
IMPORTANCE_PRIORITY = {"高": 0, "中": 1, "低": 2}

# Compound/specific telecom terms — substring match is safe for these
_TELECOM_SUB = {
    "telecom", "ufone", "telenor", "airlink", "nayatel", "wateen", "ptcl",
    "telecom sector", "telecom industry", "telecom regulation", "telecom policy",
    "telecom bill", "telecom law", "telecom amendment", "telecom license",
    "telecom revenue", "telecom market", "telecom operator", "telecom company",
    "telecom complaints", "telecom tower", "telecom tax", "telecom service",
    "mobile network", "mobile operator", "mobile subscriber", "mobile data",
    "mobile subscription", "mobile service", "mobile broadband", "mobile market",
    "mobile phone", "mobile phones",
    "internet service", "internet speed", "internet access", "internet price",
    "internet blackout", "internet outage", "internet shutdown", "internet disruption",
    "broadband", "fiber internet", "fiber optic", "fiber network",
    "spectrum", "frequency band", "frequency allocation",
    "5g network", "5g service", "5g spectrum", "5g rollout", "5g launch", "5g coverage",
    "4g network", "4g service", "lte network",
    "sim registration", "sim card", "illegal sim", "sim issuance", "sim block",
    "phone tax", "smartphone tax", "handset tax", "mobile phone tax",
    "handset import", "phone import", "device registration", "dirbs",
    "telco", "telcos", "jazzworld",
    # SBP & macro (specific compound terms only)
    "monetary policy", "policy rate", "interest rate", "central bank",
    "foreign reserves", "forex reserve", "current account",
    "inflation rate", "balance of payment", "external debt",
    "imf program", "imf review", "imf tranche", "imf loan", "imf talks",
}

# Short names requiring word-boundary check
_TELECOM_WB = {"pta", "sbp", "sco", "nrtc", "pmcl", "jazz", "zong", "sim", "isp"}

# Exclude these topics regardless of telecom keywords
_EXCLUDE = {
    "e-challan", "rickshaw", "pubg", "esports", "cricket", "psl ", "mlc ",
    "asian games", "football match",
    "car price", "automobile", "byd ", "driving license", "traffic fine", "traffic police",
    "restaurant", "food delivery", "coffee chain", "recipe",
    "real estate", "property price", "housing scheme", "home loan",
    "visa ", "passport", "travel advisory",
    "birth certificate", "death certificate", "marriage certificate",
    "lesco ", "fesco ", "electricity bill", "load shedding", "power outage",
    "hec ", "university admission", "genomics",
    "fast food", "petroleum levy", "minimum wage",
    "agriculture tax", "water charges", "textile industry",
    # SBP/bank operational or IT news unrelated to telecom or macro policy
    "new official website", "website goes live", "launch new official website",
    "relaunches website", "revamps website",
    "blocking accounts", "block bank account", "freeze account", "frozen account",
    "account freezing",
    "job openings", "new job openings", "hiring", "recruitment drive",
    "career opportunities", "vacancies announced",
}


def is_relevant(title: str) -> bool:
    t  = title.lower()
    tw = " " + t + " "
    if any(kw in tw for kw in _EXCLUDE):
        return False
    if any(kw in t for kw in _TELECOM_SUB):
        return True
    return any(" " + kw + " " in tw or tw.startswith(kw + " ") or tw.endswith(" " + kw)
               for kw in _TELECOM_WB)


# ─── Utilities ────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    ts   = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def today() -> str:
    return datetime.date.today().isoformat()


def fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            charset = "utf-8"
            ct = resp.headers.get_content_charset()
            if ct:
                charset = ct
            return resp.read().decode(charset, errors="replace")
    except Exception as e:
        log(f"  FETCH ERROR [{url}]: {e}")
        return ""


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def load_cache() -> list:
    if CACHE_FILE.exists():
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_cache(items: list) -> None:
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


# ─── Scrapers ─────────────────────────────────────────────────────────────────

def fetch_google_news(query: str, source_label: str) -> list:
    """Fetch news via Google News RSS. Used for PTA and SBP whose official sites block scrapers."""
    encoded = query.replace(" ", "+")
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en-PK&gl=PK&ceid=PK:en"
    log(f"Fetching Google News [{source_label}] …")
    raw = fetch(url)
    if not raw:
        return []

    items = []
    seen  = set()

    # Google News RSS has quirky <link> placement; use regex for reliability
    for block in re.findall(r"<item>(.*?)</item>", raw, re.S):
        title_m = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", block, re.S)
        link_m  = re.search(r"<link>(https?://[^<]+)</link>", block)
        guid_m  = re.search(r"<guid[^>]*>(https?://[^<]+)</guid>", block)
        date_m  = re.search(r"<pubDate>(.*?)</pubDate>", block)

        if not title_m:
            continue

        title = clean(title_m.group(1))
        # Google appends " - Publisher Name" — strip it
        title = re.sub(r"\s+-\s+[\w\s\.]+$", "", title).strip()
        # Prefer guid (direct article URL) over Google redirect link
        article_url = (guid_m.group(1) if guid_m else (link_m.group(1) if link_m else "")).strip()
        if not title or not article_url or article_url in seen:
            continue

        pub_date = today()
        if date_m:
            try:
                from email.utils import parsedate_to_datetime
                pub_date = parsedate_to_datetime(date_m.group(1)).strftime("%Y-%m-%d")
            except Exception:
                pass

        if pub_date < CUTOFF_DATE:
            continue

        seen.add(article_url)
        items.append({"source": source_label, "title": title, "url": article_url, "date": pub_date})

    log(f"  Google News [{source_label}]: {len(items)} items found")
    return items[:MAX_ITEMS_PER_SOURCE]


def fetch_pta() -> list:
    # PTA website is a JS SPA that blocks scrapers; use Google News instead
    return fetch_google_news(
        "PTA Pakistan telecom regulation spectrum operator 2026",
        "PTA",
    )


def fetch_sbp() -> list:
    # SBP official site blocks scrapers; use Google News instead
    return fetch_google_news(
        "SBP Pakistan monetary policy interest rate inflation reserves 2026",
        "SBP",
    )


def fetch_wp_recent(base_url: str, source_label: str) -> list:
    """Fetch recent posts via WordPress REST API (last 30 days), filtered by telecom keywords."""
    cutoff = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    after  = max(cutoff, CUTOFF_DATE) + "T00:00:00"
    items  = []
    log(f"Fetching {source_label} via WP REST API …")
    for page in range(1, 6):
        url = (f"{base_url}/wp-json/wp/v2/posts"
               f"?per_page=20&page={page}&after={after}"
               f"&_fields=title,link,date")
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as resp:
                posts = json.loads(resp.read().decode("utf-8"))
            if not posts:
                break
            for p in posts:
                title    = clean(html_lib.unescape(p.get("title", {}).get("rendered", "")))
                link     = p.get("link", "")
                pub_date = p.get("date", "")[:10]
                if not title or not link:
                    continue
                if pub_date < CUTOFF_DATE:
                    continue
                if not is_relevant(title):
                    continue
                items.append({"source": source_label, "title": title,
                               "url": link, "date": pub_date})
            time.sleep(0.2)
        except Exception as e:
            log(f"  {source_label} WP API error (page {page}): {e}")
            break
    log(f"  {source_label}: {len(items)} items found")
    return items[:MAX_ITEMS_PER_SOURCE]


def fetch_propakistani() -> list:
    return fetch_wp_recent("https://propakistani.pk", "ProPakistani")


def _parse_phoneworld_page(xml_str: str) -> list:
    """Parses a single RSS page's XML into item dicts. Each page is a complete,
    independent XML document — must be parsed separately (concatenating raw XML
    across pages produces invalid multi-root documents)."""
    page_items = []
    root = ET.fromstring(xml_str)
    channel = root.find("channel")
    if channel is None:
        return page_items

    for entry in channel.findall("item"):
        title_el = entry.find("title")
        link_el  = entry.find("link")
        date_el  = entry.find("pubDate")

        if title_el is None or link_el is None:
            continue

        title = clean(title_el.text or "")
        url   = (link_el.text or "").strip()
        if not title or not url:
            continue

        if not is_relevant(title):
            continue

        pub_date = today()
        if date_el is not None and date_el.text:
            try:
                from email.utils import parsedate_to_datetime
                pub_date = parsedate_to_datetime(date_el.text).strftime("%Y-%m-%d")
            except Exception:
                pass

        page_items.append({"source": "PhoneWorld", "title": title, "url": url, "date": pub_date})
    return page_items


def fetch_phoneworld() -> list:
    log("Fetching PhoneWorld RSS …")
    items = []
    for page in range(1, 6):
        chunk = fetch(f"https://www.phoneworld.com.pk/category/telecom-news/feed/?paged={page}")
        if not chunk or "<item>" not in chunk:
            break
        try:
            items.extend(_parse_phoneworld_page(chunk))
        except ET.ParseError as e:
            log(f"  PhoneWorld XML parse error (page {page}): {e}")
            break
        if len(items) >= MAX_ITEMS_PER_SOURCE:
            break

    log(f"  PhoneWorld: {len(items)} items found")
    return items[:MAX_ITEMS_PER_SOURCE]


def fetch_techjuice() -> list:
    return fetch_wp_recent("https://www.techjuice.pk", "TechJuice")




# ─── DeepSeek Summary ─────────────────────────────────────────────────────────

def summarize(title: str, url: str) -> dict:
    """Returns {"summary_zh": str, "importance": "高"|"中"|"低"}.
    On any failure (no key, HTTP error, bad JSON) returns empty summary and
    importance defaulted to "中" so the item still displays rather than
    silently vanishing or crashing the pipeline."""
    fallback = {"summary_zh": "", "importance": "中"}
    if not DEEPSEEK_API_KEY:
        return fallback

    payload = json.dumps({
        "model": "deepseek-chat",
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是专注巴基斯坦电信与宏观经济的资深分析师。"
                    "根据提供的新闻标题，完成两项任务，严格按JSON格式输出：\n\n"
                    "1. summary_zh：撰写200～300字的中文摘要，分2段，用\\n\\n分隔。"
                    "第1段：事件背景与核心内容（保留关键数字、百分比、机构名称）。"
                    "第2段：对巴基斯坦电信行业或宏观经济的影响与判断。"
                    "语言简练专业，不加标题前缀；"
                    "用【】标注每段最重要的结论或关键数据，每段至多2处，全文不超过4处。\n\n"
                    "2. importance：判断这条新闻对巴基斯坦电信行业竞争格局/宏观经济的重要性，"
                    "输出\"高\"、\"中\"或\"低\"之一，判断标准：\n"
                    "- 是否涉及巴基斯坦四大主流移动运营商（Jazz、Zong、Telenor、Ufone）"
                    "或SBP/PTA层面的政策监管动作——完全不涉及（如中小型固网/宽带ISP、"
                    "SCO等边缘运营商的常规新闻）应判为\"低\"；\n"
                    "- 即使涉及主流运营商或监管机构，若只是常规产品发布、常规审计、日常运营类新闻"
                    "（非监管处罚、并购、财报、重大政策变动、市场格局变化等），也应判为\"中\"而非\"高\"；\n"
                    "- 只有真正影响行业格局或宏观经济走势的重大事件才判为\"高\"。\n\n"
                    '严格输出：{"summary_zh": "...", "importance": "高/中/低"}'
                ),
            },
            {
                "role": "user",
                "content": f"请分析以下新闻：\n\n标题：{title}\n来源：{url}",
            },
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 600,
        "temperature": 0.1,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            content = json.loads(result["choices"][0]["message"]["content"])
            summary = content.get("summary_zh", "").strip()
            importance = content.get("importance", "中").strip()
            if importance not in IMPORTANCE_PRIORITY:
                importance = "中"
            return {"summary_zh": summary, "importance": importance}
    except Exception as e:
        log(f"  DeepSeek error: {e}")
        return fallback


# ─── HTML Injection ───────────────────────────────────────────────────────────

def inject_into_html(items: list) -> None:
    if not INDEX_FILE.exists():
        log("  index.html not found, skipping injection")
        return

    html = INDEX_FILE.read_text(encoding="utf-8")
    s = html.find(NEWS_START)
    e = html.find(NEWS_END)

    if s == -1 or e == -1:
        log("  Injection markers not found in index.html")
        return

    json_str  = json.dumps(items, ensure_ascii=False, indent=2)
    new_block = f"{NEWS_START}\nconst NEWS_DATA = {json_str};\n{NEWS_END}"
    INDEX_FILE.write_text(html[:s] + new_block + html[e + len(NEWS_END):], encoding="utf-8")
    log(f"  Injected {len(items)} items into index.html")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    log("=" * 50)
    log("News update started")

    cache  = load_cache()
    known  = {item["url"] for item in cache}
    log(f"Cache: {len(cache)} existing items")

    fetchers = [fetch_pta, fetch_sbp, fetch_propakistani, fetch_phoneworld,
                fetch_techjuice]
    new_items: list = []

    for fn in fetchers:
        try:
            for item in fn():
                if item["url"] not in known:
                    new_items.append(item)
                    known.add(item["url"])
        except Exception as e:
            log(f"  Source error ({fn.__name__}): {e}")
        time.sleep(1)

    log(f"New items: {len(new_items)}")

    # Re-summarise cached items that have an empty summary_zh (unrelated to the
    # importance tag — old cached items without "importance" are left as-is;
    # the display sort just treats a missing tag as "中" via .get() fallback)
    retry_items = [i for i in cache if not i.get("summary_zh", "").strip()]
    if retry_items:
        log(f"Re-summarising {len(retry_items)} cached items with empty summaries …")
    for item in retry_items:
        log(f"  Re-summarising: {item['title'][:70]} …")
        result = summarize(item["title"], item["url"])
        item["summary_zh"] = result["summary_zh"]
        item["importance"] = result["importance"]
        time.sleep(0.5)

    for item in new_items:
        log(f"  Summarising: {item['title'][:70]} …")
        result = summarize(item["title"], item["url"])
        item["summary_zh"] = result["summary_zh"]
        item["importance"] = result["importance"]
        time.sleep(0.5)

    # Prepend new items and save
    cache = new_items + cache
    # Drop irrelevant articles that slipped into cache previously
    cache = [i for i in cache if is_relevant(i.get("title", ""))]
    save_cache(cache)
    log(f"Cache saved: {len(cache)} total items")

    # Inject into index.html: per day, sorted by importance then source priority,
    # deduplicated, max MAX_PER_DAY
    from collections import defaultdict as _dd
    _by_day: dict = _dd(list)
    for _it in cache:
        _by_day[_it.get("date", "")].append(_it)
    display: list = []
    for _d in sorted(_by_day.keys(), reverse=True):
        day_sorted = sorted(
            _by_day[_d],
            key=lambda x: (
                IMPORTANCE_PRIORITY.get(x.get("importance", "中"), 1),
                SOURCE_PRIORITY.get(x.get("source", ""), 99),
            ),
        )
        # Deduplicate same-day articles with very similar titles (keep higher-priority source)
        seen_titles: set = set()
        deduped: list = []
        for _it in day_sorted:
            _key = re.sub(r"[^a-z0-9]", "", _it.get("title", "").lower())[:60]
            if _key not in seen_titles:
                seen_titles.add(_key)
                deduped.append(_it)
        display.extend(deduped[:MAX_PER_DAY])
    display = display[:MAX_DISPLAY_ITEMS]
    inject_into_html(display)

    log("News update complete")
    log("=" * 50)


if __name__ == "__main__":
    main()
