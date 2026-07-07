#!/usr/bin/env python3
"""
Fetches latest Pakistan telecom/economy news from 5 sources,
generates Chinese summaries via DeepSeek, and injects NEWS_DATA into index.html.

Sources: PTA, SBP, PBS, ProPakistani (RSS), Business Recorder
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
MAX_PER_DAY          = 8
# Minimum distinct sources required in a day's display (when the day's candidate
# pool actually has that many distinct sources available) — prevents one busy
# source (e.g. PhoneWorld having a big news day) from crowding out every other
# outlet entirely.
MIN_SOURCES_PER_DAY  = 3
# If a day's candidate pool doesn't actually have MIN_SOURCES_PER_DAY distinct
# sources available, showing a full MAX_PER_DAY items would just be one or two
# outlets' entire output for the day, not a diverse cross-section — so the cap
# drops to LOW_DIVERSITY_CAP instead. This is a real fallback, not a target:
# don't invent extra items to reach it, and don't force distinct sources that
# don't exist that day.
LOW_DIVERSITY_CAP    = 5
CUTOFF_DATE          = "2026-01-01"

# Source priority for per-day display ranking (lower = higher priority)
SOURCE_PRIORITY = {"PTA": 0, "ProPakistani": 1, "SBP": 2, "BusinessRecorder": 3, "TechJuice": 4}

# Importance ranking for per-day display (lower = shown first); see summarize()
IMPORTANCE_PRIORITY = {"高": 0, "中": 1, "低": 2}

# Titles mentioning PTA are front-loaded in the per-day display, but capped so
# they don't crowd out every other source when PTA has a busy news day.
MAX_PTA_PER_DAY = 3

# Only run the cross-source dedup pass (see mark_duplicates()) on days within
# this many days of today, to bound API cost as the cache grows.
DEDUP_LOOKBACK_DAYS = 3

# Deterministic entity-overlap fallback for same-event dedup (backs up the LLM
# pass, which is non-deterministic and occasionally misses an obvious duplicate
# even at temperature=0 — e.g. it once let both ProPakistani's "PTCL's Chief
# People Officer Umer Farid Joins PSTD Board of Governors" and TechJuice's "PTCL
# CPO Umer Farid Appointed to PSTD Board of Governors" through). Two same-day
# titles are judged the same event when they share at least
# ENTITY_OVERLAP_MIN_RARE tokens that are *rare that day* (appear in at most
# ENTITY_RARE_DF_MAX of the day's titles) — high-signal names like "Umer",
# "Farid", "PSTD" rather than high-frequency topic words like "Ufone"/"Merger"
# that many of the day's stories share. Deliberately conservative (miss rather
# than wrongly merge two different stories on the same topic).
ENTITY_OVERLAP_MIN_RARE = 3
ENTITY_RARE_DF_MAX      = 3
_DEDUP_STOP = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "after",
    "before", "will", "can", "could", "may", "might", "be", "is", "are", "was",
    "were", "as", "at", "by", "with", "from", "into", "over", "under", "up",
    "out", "off", "its", "their", "new", "get", "gets", "face", "faces", "amid",
    "than", "more", "less", "how", "what", "why", "when", "who", "until",
    "further", "notice", "existing", "continue", "expected", "rise", "change",
    "pakistan", "pakistani", "pakistans",
}

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


def mentions_pta(title: str) -> bool:
    return re.search(r"\bpta\b", title, re.IGNORECASE) is not None


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


def fetch_article_text(url: str, max_chars: int = 3000) -> str:
    """Best-effort extraction of visible article text from a live page, so
    summarize() can ground its summary in real content instead of guessing
    from the title alone. Returns "" on any failure or if the page yields
    implausibly little text — callers must treat empty as 'no content
    available, fall back to title-only summarization'."""
    try:
        html = fetch(url, timeout=15)
        if not html:
            return ""
        html = re.sub(r"<(script|style|nav|footer|header)\b[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", html)
        text = html_lib.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < 200:
            return ""
        return text[:max_chars]
    except Exception as e:
        log(f"  Article content fetch failed ({url}): {e}")
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


def fetch_business_recorder() -> list:
    """Business Recorder's Business & Finance RSS — Pakistan's oldest financial
    daily, replaced PhoneWorld (2026-07-02) after a quality complaint: PhoneWorld
    was found to occasionally republish stale/outdated stories under a fresh
    date (e.g. an article claiming the 5G spectrum auction "hadn't happened yet"
    months after it actually concluded in March 2026). This is a general
    business/finance feed (not telecom-specific), so is_relevant() filtering
    matters a lot here — most items are unrelated (forex, gold, general markets)."""
    log("Fetching Business Recorder RSS …")
    items = []
    xml_str = fetch("https://www.brecorder.com/feeds/business")
    if not xml_str:
        log("  Business Recorder: 0 items found")
        return items

    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError as e:
        log(f"  Business Recorder XML parse error: {e}")
        return items

    channel = root.find("channel")
    if channel is None:
        log("  Business Recorder: 0 items found")
        return items

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

        items.append({"source": "BusinessRecorder", "title": title, "url": url, "date": pub_date})
        if len(items) >= MAX_ITEMS_PER_SOURCE:
            break

    log(f"  Business Recorder: {len(items)} items found")
    return items[:MAX_ITEMS_PER_SOURCE]


def fetch_techjuice() -> list:
    return fetch_wp_recent("https://www.techjuice.pk", "TechJuice")




# ─── DeepSeek Summary ─────────────────────────────────────────────────────────

def summarize(title: str, url: str, article_text: str = "") -> dict:
    """Returns {"summary_zh": str, "importance": "高"|"中"|"低"}.
    On any failure (no key, HTTP error, bad JSON) returns empty summary and
    importance defaulted to "中" so the item still displays rather than
    silently vanishing or crashing the pipeline.

    article_text (if provided by fetch_article_text()) is the actual scraped
    page text — the summary MUST be grounded in it. DeepSeek has no ability to
    fetch the url itself; passing only title+url previously let it silently
    fabricate plausible-sounding but fictitious numbers/dates. When no content
    could be scraped, the prompt explicitly forbids inventing specifics."""
    fallback = {"summary_zh": "", "importance": "中"}
    if not DEEPSEEK_API_KEY:
        return fallback

    if article_text:
        grounding = (
            "下面提供了这条新闻的正文节选，请【严格根据正文内容】撰写摘要和判断重要性，"
            "正文中没有的具体数字、百分比、日期、人名一律不得编造。"
        )
        user_content = f"标题：{title}\n来源：{url}\n\n正文节选：\n{article_text}"
    else:
        grounding = (
            "本次未能抓取到正文，只能看到标题，你没有能力访问链接内容。"
            "摘要只能围绕标题明确传达的信息展开合理的背景说明和行业影响分析，"
            "严禁编造标题中没有的具体数字、百分比、日期等看似精确实则无依据的细节。"
        )
        user_content = f"标题：{title}\n来源：{url}"

    payload = json.dumps({
        "model": "deepseek-chat",
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是专注巴基斯坦电信与宏观经济的资深分析师。"
                    f"{grounding}"
                    "完成两项任务，严格按JSON格式输出：\n\n"
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
                "content": user_content,
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


def llm_dedup_groups(items: list) -> list:
    """Ask DeepSeek to group same-day titles that report the same underlying
    event with different wording (the cheap string-similarity dedup in main()
    only catches near-identical titles). Returns a list of index groups, e.g.
    [[0, 3], [5, 7]]; [] on error or when nothing matches. This is the main
    recall pass but is non-deterministic — mark_duplicates() unions it with the
    deterministic entity_overlap_groups() fallback so an occasional LLM miss
    doesn't let a duplicate through."""
    if len(items) < 2 or not DEEPSEEK_API_KEY:
        return []

    listing = "\n".join(f"{i}. [{it['source']}] {it['title']}" for i, it in enumerate(items))
    payload = json.dumps({
        "model": "deepseek-chat",
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是新闻编辑助手。下面是同一天抓取到的新闻标题列表（编号从0开始），"
                    "可能来自不同网站，同一新闻事件常被不同网站用不同措辞报道。"
                    "判断是否同一事件的标准：同一主体 + 同一动作 + 同一对象，"
                    "即使措辞不同也算同一事件——注意识别：\n"
                    "· 缩写与全称（如 CPO = Chief People Officer，MoU = 谅解备忘录）；\n"
                    "· 同义动词（Joins / Appointed to / Named to / Elected to 表示同一任命）；\n"
                    "· 主动被动、词序调整、增删修饰语。\n"
                    "示例：「PTCL's Chief People Officer Umer Farid Joins PSTD Board of Governors」"
                    "与「PTCL CPO Umer Farid Appointed to PSTD Board of Governors」是同一事件；"
                    "「IHC Clears Telenor's Merger Into Ufone」与「IHC Approves Telenor-Ufone Merger」是同一事件。"
                    "但同一话题下的不同角度（如合并后的『资费上涨』与『员工裁员』）不是同一事件。\n"
                    "请找出描述同一事件的条目，按分组返回编号（每组至少2条），"
                    "完全没有重复事件时返回空数组。"
                    '严格按JSON格式输出：{"duplicate_groups": [[0,3],[5,7]]}'
                ),
            },
            {"role": "user", "content": listing},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 300,
        "temperature": 0,
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
            return content.get("duplicate_groups", [])
    except Exception as e:
        log(f"  DeepSeek dedup error: {e}")
        return []


def _title_tokens(title: str) -> set:
    words = re.findall(r"[a-z0-9]+", title.lower())
    return {w for w in words if len(w) > 2 and w not in _DEDUP_STOP}


def entity_overlap_groups(items: list) -> list:
    """Deterministic same-event detection backing up the LLM pass: two same-day
    titles are grouped when they share at least ENTITY_OVERLAP_MIN_RARE tokens
    that are rare that day (document frequency <= ENTITY_RARE_DF_MAX). Rare
    shared tokens are high-signal (names, org acronyms) rather than the topic
    words many of the day's titles share, so this stays conservative. Returns
    index groups like llm_dedup_groups()."""
    toks = [_title_tokens(it.get("title", "")) for it in items]
    df: dict = {}
    for ts in toks:
        for w in ts:
            df[w] = df.get(w, 0) + 1

    groups, used = [], set()
    for i in range(len(items)):
        if i in used:
            continue
        grp = [i]
        for j in range(i + 1, len(items)):
            if j in used:
                continue
            rare_shared = [w for w in (toks[i] & toks[j]) if df.get(w, 0) <= ENTITY_RARE_DF_MAX]
            if len(rare_shared) >= ENTITY_OVERLAP_MIN_RARE:
                grp.append(j)
                used.add(j)
        if len(grp) >= 2:
            used.update(grp)
            groups.append(grp)
    return groups


def mark_duplicates(cache: list) -> None:
    """Persist *only the deterministic* entity-overlap dedup decisions onto the
    cache: within each of the last DEDUP_LOOKBACK_DAYS days, tag every non-best
    copy of an entity-overlap group with `dup_of` (the URL of the kept item);
    display skips tagged items. Persisting the decision (vs recomputing every
    run) is what stops an already-deduped story from resurfacing.

    Deliberately does NOT persist the LLM grouping: the LLM is non-deterministic
    and, worse, sometimes over-merges different stories on the same topic (e.g.
    treating a merger's "tariffs rise", "rebranding halted" and "packages
    continue?" as one event) — persisting that would permanently drop distinct
    news. The LLM pass stays a per-run, non-persisted display filter (see
    main()), so an over-merge only affects one run and self-corrects next time.
    The entity fallback is conservative enough never to over-merge, so persisting
    it is safe and keeps decisions idempotent."""
    from collections import defaultdict
    cutoff = (datetime.date.today() - datetime.timedelta(days=DEDUP_LOOKBACK_DAYS)).isoformat()
    by_day: dict = defaultdict(list)
    for it in cache:
        if it.get("date", "") >= cutoff and it.get("summary_zh", "").strip():
            by_day[it["date"]].append(it)

    total_tagged = 0
    for day, day_items in by_day.items():
        active = [it for it in day_items if not it.get("dup_of")]
        if len(active) < 2:
            continue
        active.sort(key=lambda x: (
            IMPORTANCE_PRIORITY.get(x.get("importance", "中"), 1),
            SOURCE_PRIORITY.get(x.get("source", ""), 99),
        ))
        groups = entity_overlap_groups(active)

        # Union all groups into connected components so LLM and entity groupings
        # that overlap collapse to one; keep the lowest index (best-ranked).
        parent = list(range(len(active)))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for group in groups:
            g = [i for i in group if isinstance(i, int) and 0 <= i < len(active)]
            for k in g[1:]:
                ra, rb = find(g[0]), find(k)
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)

        comp: dict = defaultdict(list)
        for i in range(len(active)):
            comp[find(i)].append(i)
        for members in comp.values():
            if len(members) < 2:
                continue
            members.sort()
            keep = active[members[0]]
            keep_id = keep.get("url", "") or keep.get("title", "")
            for idx in members[1:]:
                dup = active[idx]
                if not dup.get("dup_of"):
                    dup["dup_of"] = keep_id
                    total_tagged += 1

    if total_tagged:
        log(f"  Cross-source dedup: tagged {total_tagged} duplicate-event item(s) with dup_of")


def ensure_source_diversity(day_display: list, candidates: list, min_sources: int) -> list:
    """If day_display ended up with fewer than min_sources distinct sources but
    candidates (the full deduped pool for that day) actually has more sources
    available, swap in the best-ranked item from an unrepresented source —
    dropping the current lowest-ranked item in day_display to keep the same
    length. candidates must already be sorted by (importance, source priority).
    No-ops if the day's real candidate pool simply doesn't have enough distinct
    sources to satisfy the minimum."""
    have = {it.get("source", "") for it in day_display}
    if len(have) >= min_sources:
        return day_display

    shown_urls = {it.get("url", "") for it in day_display}
    for cand in candidates:
        if cand.get("url", "") in shown_urls:
            continue
        if cand.get("source", "") in have:
            continue
        # found the best-ranked item from a source not yet represented
        if day_display:
            day_display = day_display[:-1]  # drop the current lowest-ranked slot
        day_display = day_display + [cand]
        have.add(cand.get("source", ""))
        if len(have) >= min_sources:
            break
    return day_display


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

    fetchers = [fetch_pta, fetch_sbp, fetch_propakistani, fetch_business_recorder,
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
        article_text = fetch_article_text(item["url"])
        result = summarize(item["title"], item["url"], article_text)
        item["summary_zh"] = result["summary_zh"]
        item["importance"] = result["importance"]
        time.sleep(0.5)

    for item in new_items:
        log(f"  Summarising: {item['title'][:70]} …")
        article_text = fetch_article_text(item["url"])
        result = summarize(item["title"], item["url"], article_text)
        item["summary_zh"] = result["summary_zh"]
        item["importance"] = result["importance"]
        time.sleep(0.5)

    # Prepend new items and save
    cache = new_items + cache
    # Drop irrelevant articles that slipped into cache previously
    cache = [i for i in cache if is_relevant(i.get("title", ""))]
    save_cache(cache)
    log(f"Cache saved: {len(cache)} total items")

    # Persist same-event dedup decisions (dup_of) onto the cache so an already
    # deduplicated story doesn't resurface when the LLM grouping wobbles between
    # runs. Combines the LLM pass with a deterministic entity-overlap fallback.
    mark_duplicates(cache)
    save_cache(cache)

    # Inject into index.html: per day, sorted by importance then source priority,
    # deduplicated, PTA-titled items front-loaded (capped), max MAX_PER_DAY
    from collections import defaultdict as _dd
    _by_day: dict = _dd(list)
    for _it in cache:
        # Items whose summarize() call errored/timed out (e.g. DeepSeek timeout)
        # are left with an empty summary_zh and picked up by the retry_items
        # pass on the next run — they must not show as a blank card in the
        # meantime, so they're excluded from display until they have content.
        if not _it.get("summary_zh", "").strip():
            continue
        # Items tagged as same-event duplicates by mark_duplicates() (the
        # deterministic entity-overlap pass) are dropped from display here; that
        # decision is persisted on the cache (dup_of) so it stays stable across
        # runs. The LLM pass below is an additional, non-persisted per-run filter.
        if _it.get("dup_of"):
            continue
        _by_day[_it.get("date", "")].append(_it)

    # The LLM same-event dedup runs per-run on recent days only (bounded API
    # cost) and is NOT persisted — it catches wording-very-different duplicates
    # the entity fallback misses, but its occasional over-merges must not be
    # baked onto the cache, so it only filters the current run's display.
    dedup_cutoff = (datetime.date.today() - datetime.timedelta(days=DEDUP_LOOKBACK_DAYS)).isoformat()

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

        # LLM same-event dedup as a per-run (non-persisted) display filter for
        # recent days — catches wording-very-different duplicates the persisted
        # entity-overlap pass misses. deduped is already sorted by (importance,
        # source), so keeping the lowest index in each group keeps the best copy.
        if _d >= dedup_cutoff and len(deduped) > 1:
            _drop: set = set()
            for _grp in llm_dedup_groups(deduped):
                _valid = sorted(i for i in _grp if isinstance(i, int) and 0 <= i < len(deduped))
                if len(_valid) >= 2:
                    _drop.update(_valid[1:])
            if _drop:
                deduped = [it for i, it in enumerate(deduped) if i not in _drop]

        # The display cap itself scales with how many distinct sources the day
        # actually has to offer: a day where only 1-2 outlets published
        # anything shouldn't be padded out to MAX_PER_DAY just because one of
        # them was prolific — that's one or two outlets' full output, not a
        # diverse cross-section. Only days with genuine multi-source coverage
        # get the full cap.
        _distinct_sources = len({it.get("source", "") for it in deduped})
        day_cap = MAX_PER_DAY if _distinct_sources >= MIN_SOURCES_PER_DAY else LOW_DIVERSITY_CAP

        # PTA-titled items are front-loaded but capped so they don't crowd out
        # every other source on a busy PTA news day.
        pta_items    = [it for it in deduped if mentions_pta(it.get("title", ""))]
        other_items  = [it for it in deduped if not mentions_pta(it.get("title", ""))]
        day_display  = pta_items[:MAX_PTA_PER_DAY]
        leftover     = sorted(
            pta_items[MAX_PTA_PER_DAY:] + other_items,
            key=lambda x: (
                IMPORTANCE_PRIORITY.get(x.get("importance", "中"), 1),
                SOURCE_PRIORITY.get(x.get("source", ""), 99),
            ),
        )
        day_display += leftover[:max(0, day_cap - len(day_display))]

        day_sorted_all = sorted(
            deduped,
            key=lambda x: (
                IMPORTANCE_PRIORITY.get(x.get("importance", "中"), 1),
                SOURCE_PRIORITY.get(x.get("source", ""), 99),
            ),
        )
        day_display = ensure_source_diversity(day_display, day_sorted_all, MIN_SOURCES_PER_DAY)

        display.extend(day_display)
    display = display[:MAX_DISPLAY_ITEMS]
    inject_into_html(display)

    log("News update complete")
    log("=" * 50)


if __name__ == "__main__":
    main()
