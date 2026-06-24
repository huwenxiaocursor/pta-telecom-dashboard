#!/usr/bin/env python3
"""
Fetches latest Pakistan telecom/economy news from 5 sources,
generates Chinese summaries via DeepSeek, and injects NEWS_DATA into index.html.

Sources: PTA, SBP, PBS, ProPakistani (RSS), PhoneWorld
"""

import datetime
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
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

MAX_ITEMS_PER_SOURCE = 15
MAX_DISPLAY_ITEMS    = 300


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

def fetch_pta() -> list:
    log("Fetching PTA …")
    html = fetch("https://www.pta.gov.pk/en/media-center/press-releases")
    if not html:
        return []

    items = []
    seen  = set()

    # Pattern 1: full URL inside href
    for url, title in re.findall(
        r'href="(https?://(?:www\.)?pta\.gov\.pk/en/media-center/press-releases/[^"#?]+)"[^>]*>\s*([^<]{10,250})',
        html, re.S
    ):
        title = clean(title)
        if title and url not in seen:
            seen.add(url)
            items.append({"source": "PTA", "title": title, "url": url, "date": today()})

    # Pattern 2: relative URL
    for rel, title in re.findall(
        r'href="(/en/media-center/press-releases/[^"#?]+)"[^>]*>\s*([^<]{10,250})',
        html, re.S
    ):
        url   = "https://www.pta.gov.pk" + rel
        title = clean(title)
        if title and url not in seen:
            seen.add(url)
            items.append({"source": "PTA", "title": title, "url": url, "date": today()})

    log(f"  PTA: {len(items)} items found")
    return items[:MAX_ITEMS_PER_SOURCE]


def fetch_sbp() -> list:
    log("Fetching SBP …")
    html = fetch("https://www.sbp.org.pk/press/index.htm")
    if not html:
        return []

    items = []
    seen  = set()

    # SBP uses relative links like PR/2026/Jun/PR1.htm or similar
    for href, title in re.findall(
        r'href="([^"]+\.(?:htm|html|pdf|aspx))"[^>]*>\s*([^<]{15,250})',
        html, re.S
    ):
        title = clean(title)
        if not title or len(title) < 15:
            continue
        # Build absolute URL
        if href.startswith("http"):
            url = href
        elif href.startswith("/"):
            url = "https://www.sbp.org.pk" + href
        else:
            url = "https://www.sbp.org.pk/press/" + href.lstrip("./")

        if "sbp.org.pk" not in url:
            continue
        if url not in seen:
            seen.add(url)
            items.append({"source": "SBP", "title": title, "url": url, "date": today()})

    log(f"  SBP: {len(items)} items found")
    return items[:MAX_ITEMS_PER_SOURCE]


def fetch_propakistani() -> list:
    log("Fetching ProPakistani RSS …")
    xml_str = fetch("https://propakistani.pk/feed/")
    if not xml_str:
        return []

    TELECOM_KEYWORDS = {
        "telecom", "pta", "jazz", "ufone", "zong", "telenor", "sco",
        "5g", "4g", "lte", "mobile", "internet", "broadband", "spectrum",
        "sbp", "economy", "pkr", "rupee", "pakistan economy", "imf",
        "frequency", "license", "regulation", "operator",
    }

    items = []
    try:
        root = ET.fromstring(xml_str)
        channel = root.find("channel")
        if channel is None:
            return []

        for entry in channel.findall("item"):
            title_el = entry.find("title")
            link_el  = entry.find("link")
            date_el  = entry.find("pubDate")

            if title_el is None or link_el is None:
                continue

            title = clean(title_el.text or "")
            url   = clean(link_el.text or "")
            if not title or not url:
                continue

            # Relevance filter
            if not any(kw in title.lower() for kw in TELECOM_KEYWORDS):
                continue

            pub_date = today()
            if date_el is not None and date_el.text:
                try:
                    from email.utils import parsedate_to_datetime
                    pub_date = parsedate_to_datetime(date_el.text).strftime("%Y-%m-%d")
                except Exception:
                    pass

            items.append({"source": "ProPakistani", "title": title, "url": url, "date": pub_date})

    except ET.ParseError as e:
        log(f"  ProPakistani XML parse error: {e}")

    log(f"  ProPakistani: {len(items)} items found")
    return items[:MAX_ITEMS_PER_SOURCE]


def fetch_phoneworld() -> list:
    log("Fetching PhoneWorld …")
    html = fetch("https://phoneworld.com.pk/")
    if not html:
        return []

    items = []
    seen  = set()

    # WordPress-style URLs: /YYYY/MM/DD/slug/
    for url, title in re.findall(
        r'href="(https?://phoneworld\.com\.pk/\d{4}/\d{2}/\d{2}/[^"]+)"[^>]*>\s*([^<]{10,250})',
        html, re.S
    ):
        title = clean(title)
        if not title:
            continue
        date_m = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", url)
        pub_date = f"{date_m.group(1)}-{date_m.group(2)}-{date_m.group(3)}" if date_m else today()
        if url not in seen:
            seen.add(url)
            items.append({"source": "PhoneWorld", "title": title, "url": url, "date": pub_date})

    # Fallback: any internal link with a meaningful title
    if not items:
        for href, title in re.findall(
            r'href="(https?://phoneworld\.com\.pk/[^"]+)"[^>]*>\s*([^<]{15,250})',
            html, re.S
        ):
            title = clean(title)
            if not title or href in seen:
                continue
            if any(skip in href for skip in ["#", "page", "category", "tag", "author"]):
                continue
            seen.add(href)
            items.append({"source": "PhoneWorld", "title": title, "url": href, "date": today()})

    log(f"  PhoneWorld: {len(items)} items found")
    return items[:MAX_ITEMS_PER_SOURCE]


def fetch_techjuice() -> list:
    log("Fetching TechJuice RSS …")
    xml_str = fetch("https://techjuice.pk/feed/")
    if not xml_str:
        return []

    TELECOM_KEYWORDS = {
        "telecom", "pta", "jazz", "ufone", "zong", "telenor", "sco",
        "5g", "4g", "lte", "mobile", "internet", "broadband", "spectrum",
        "sbp", "economy", "pkr", "rupee", "imf", "frequency", "license",
        "regulation", "operator", "sim", "fiber", "pakistan telecom",
    }

    items = []
    try:
        root = ET.fromstring(xml_str)
        channel = root.find("channel")
        if channel is None:
            return []

        for entry in channel.findall("item"):
            title_el = entry.find("title")
            link_el  = entry.find("link")
            date_el  = entry.find("pubDate")

            if title_el is None or link_el is None:
                continue

            title = clean(title_el.text or "")
            url   = clean(link_el.text or "")
            if not title or not url:
                continue

            if not any(kw in title.lower() for kw in TELECOM_KEYWORDS):
                continue

            pub_date = today()
            if date_el is not None and date_el.text:
                try:
                    from email.utils import parsedate_to_datetime
                    pub_date = parsedate_to_datetime(date_el.text).strftime("%Y-%m-%d")
                except Exception:
                    pass

            items.append({"source": "TechJuice", "title": title, "url": url, "date": pub_date})

    except ET.ParseError as e:
        log(f"  TechJuice XML parse error: {e}")

    log(f"  TechJuice: {len(items)} items found")
    return items[:MAX_ITEMS_PER_SOURCE]


def fetch_profit_pk() -> list:
    log("Fetching Profit Pakistan (sitemap) …")
    # Must contain at least one of these to be included
    INCLUDE = {
        "telecom", "pta", "jazz", "ufone", "zong", "telenor", "sco",
        "5g", "4g", "lte", "mobile", "internet", "broadband", "spectrum",
        "sim", "fiber", "jazzcash", "digital-bank", "digital-payment",
        "frequency", "license", "regulation", "operator", "smartphone",
        "handset", "phone-tax", "phone-import", "airlink",
        "sbp-monetary", "monetary-policy", "policy-rate", "sbp-rate",
        "sbp-reserve", "sbp-digital", "sbp-payment", "sbp-survey",
        "forex-reserve", "foreign-exchange", "remittance",
        "imf-pakistan", "imf-programme", "imf-loan", "imf-review",
    }
    # If slug contains any of these, skip regardless
    EXCLUDE = {
        "energies", "gas-supply", "gas-pipeline", "oil-supply", "ogdcl",
        "mari-", "sngpl", "ssgc", "ppib", "ntdc", "petroleum",
        "lng-", "coal-", "wheat-", "sugar-", "fertilizer",
        "agriculture", "livestock", "poultry", "beef-", "rice-",
        "ipo-book", "book-building",
    }

    items = []
    seen  = set()
    cutoff = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()

    for i in range(1, 8):
        url = f"https://profit.pakistantoday.com.pk/sitemaps/sitemap-articles-{i}.xml"
        xml = fetch(url)
        if not xml:
            break

        entries = re.findall(
            r"<loc>(https?://profit\.pakistantoday\.com\.pk/(\d{4})/(\d{2})/(\d{2})/([^<]+))</loc>\s*<lastmod>([^<]+)</lastmod>",
            xml,
        )
        for full_url, yr, mo, dy, slug, lastmod in entries:
            pub_date = f"{yr}-{mo}-{dy}"
            if pub_date < cutoff:
                break  # sitemaps are newest-first; stop when too old
            if full_url in seen:
                continue
            if any(ex in slug for ex in EXCLUDE):
                continue
            if not any(kw in slug for kw in INCLUDE):
                continue
            seen.add(full_url)
            title = slug.replace("-", " ").title()
            items.append({"source": "Profit.pk", "title": title, "url": full_url, "date": pub_date})

        if items and entries and entries[-1][5] < cutoff:
            break  # all remaining sitemaps will be older

    log(f"  Profit.pk: {len(items)} items found")
    return items[:MAX_ITEMS_PER_SOURCE]


# ─── DeepSeek Summary ─────────────────────────────────────────────────────────

def summarize(title: str, url: str) -> str:
    if not DEEPSEEK_API_KEY:
        return ""

    payload = json.dumps({
        "model": "deepseek-chat",
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是专注巴基斯坦电信与宏观经济的资深分析师。"
                    "根据提供的新闻标题，撰写200～300字的中文摘要，分2段输出。"
                    "第1段：事件背景与核心内容（保留关键数字、百分比、机构名称）。"
                    "第2段：对巴基斯坦电信行业或宏观经济的影响与判断。"
                    "要求：语言简练专业，直接输出正文，段间空一行，不加标题前缀；"
                    "用【】标注每段最重要的结论或关键数据，每段至多2处，全文不超过4处。"
                ),
            },
            {
                "role": "user",
                "content": f"请为以下新闻撰写中文摘要：\n\n标题：{title}\n来源：{url}",
            },
        ],
        "max_tokens": 500,
        "temperature": 0.3,
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
            return result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log(f"  DeepSeek error: {e}")
        return ""


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
                fetch_techjuice, fetch_profit_pk]
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

    # Re-summarise cached items that have an empty summary_zh
    retry_items = [i for i in cache if not i.get("summary_zh", "").strip()]
    if retry_items:
        log(f"Re-summarising {len(retry_items)} cached items with empty summaries …")
    for item in retry_items:
        log(f"  Re-summarising: {item['title'][:70]} …")
        item["summary_zh"] = summarize(item["title"], item["url"])
        time.sleep(0.5)

    for item in new_items:
        log(f"  Summarising: {item['title'][:70]} …")
        item["summary_zh"] = summarize(item["title"], item["url"])
        time.sleep(0.5)

    # Prepend new items and save
    cache = new_items + cache
    save_cache(cache)
    log(f"Cache saved: {len(cache)} total items")

    # Inject most-recent items into index.html (sorted by date desc)
    display = sorted(cache, key=lambda x: x.get("date", ""), reverse=True)[:MAX_DISPLAY_ITEMS]
    inject_into_html(display)

    log("News update complete")
    log("=" * 50)


if __name__ == "__main__":
    main()
