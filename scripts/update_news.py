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
import subprocess
import time
import xml.etree.ElementTree as ET
from typing import Union

BASE_DIR   = pathlib.Path(__file__).resolve().parent
CACHE_FILE = BASE_DIR / "news_cache.json"
INDEX_FILE = BASE_DIR.parent / "index.html"
LOG_FILE   = BASE_DIR / "news_update_log.txt"

NEWS_START = "// ===AUTO-NEWS-START==="
NEWS_END   = "// ===AUTO-NEWS-END==="

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

# —— VPN 代理配置（curl 原生支持 HTTP_PROXY / HTTPS_PROXY 环境变量）——
# 如果代理不可达则自动跳过，避免 VPN 没开时连 TechJuice 也抓不了
_proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or ""
if _proxy_url:
    import socket
    _proxy_host = _proxy_url.split("://")[-1].split(":")[0]
    _proxy_port = int(_proxy_url.split(":")[-1])
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect((_proxy_host, _proxy_port))
        s.close()
        os.environ.setdefault("HTTP_PROXY", _proxy_url)
        os.environ.setdefault("HTTPS_PROXY", _proxy_url)
    except Exception:
        # 代理不可用 → 直连。必须同时从 os.environ 移除，否则 curl 子进程
        # 仍会继承 HTTP_PROXY/HTTPS_PROXY 去连不存在的代理端口（exit 7）
        _proxy_url = ""
        os.environ.pop("HTTP_PROXY", None)
        os.environ.pop("HTTPS_PROXY", None)
        os.environ.pop("http_proxy", None)
        os.environ.pop("https_proxy", None)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# 默认 False：改过滤规则只影响以后抓到的新闻，不回溯清洗历史缓存。
# 命令行加 --reclean 才会按当前规则重筛整份 news_cache.json。
RECLEAN_CACHE = False

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
# 抓取日期下限：早于这天的一律不收。2026-08-13 从 2026-01-01 上调到 2026-08-01
# ——修好 Google News 的排序/时间窗问题后，PTA、SBP 两个源积压的历史条目会一次性
# 涌进来，而用户只要 8 月及以后的。已入库的历史条目不受影响（过滤只作用于新抓取）。
CUTOFF_DATE          = "2026-08-01"

# Source priority for per-day display ranking (lower = higher priority)
SOURCE_PRIORITY = {"PTA": 0, "ProPakistani": 1, "SBP": 2, "Dawn": 3,
                   "BusinessRecorder": 4, "TechJuice": 5}

# Importance ranking for per-day display (lower = shown first); see summarize()
IMPORTANCE_PRIORITY = {"高": 0, "中": 1, "低": 2}

# Titles mentioning PTA are front-loaded in the per-day display, but capped so
# they don't crowd out every other source when PTA has a busy news day.
# 2026-08-13 从 3 提到 5（用户要求）：修好 Google News 取数后 PTA 源恢复正常，
# 8-12 那天有 9 条 PTA 候选却只排上 2 条。每日总数仍是 MAX_PER_DAY(8)，
# 所以最多占 5 席、至少给其他来源留 3 席。
MAX_PTA_PER_DAY = 5

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
# How much of each summary_zh goes into the LLM dedup prompt. Long enough to
# carry the lede's subject/verb/object and its first figures (that is what makes
# same-event obvious when the headlines don't), short enough that the whole
# recent window stays a cheap single call.
DEDUP_SUMMARY_CHARS = 100
_DEDUP_STOP = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "after",
    "before", "will", "can", "could", "may", "might", "be", "is", "are", "was",
    "were", "as", "at", "by", "with", "from", "into", "over", "under", "up",
    "out", "off", "its", "their", "new", "get", "gets", "face", "faces", "amid",
    "than", "more", "less", "how", "what", "why", "when", "who", "until",
    "further", "notice", "existing", "continue", "expected", "rise", "change",
    "pakistan", "pakistani", "pakistans",
    # Generic beat vocabulary. These are *topic* words, not the person/org names
    # the rare-token test is meant to key on, but in a 3-day window an ordinary
    # topic can stay under ENTITY_RARE_DF_MAX and get treated as a high-signal
    # entity. Real over-merge (2026-07-22): Dawn "Mobile phone imports top
    # Rs520bn in FY26" and ProPakistani "Customs Rejects Claims of Surge in
    # Finished Mobile Phone Imports" shared exactly {mobile, phone, imports} —
    # hitting the bar of 3 — and the second story is Customs *rebutting* the
    # first, so persisting that merge silently deleted the original report.
    # Distinctive figures (rs740m, 900000) and names stay in play; only the
    # generic nouns drop out, which keeps this layer as conservative as its
    # docstring claims.
    "mobile", "phone", "phones", "smartphone", "smartphones", "handset",
    "handsets", "import", "imports", "export", "exports", "telecom", "telecoms",
    "telco", "telcos", "cellular", "internet", "broadband", "network",
    "networks", "spectrum", "data", "user", "users", "subscriber", "subscribers",
    "customer", "customers", "service", "services", "market", "markets",
    "price", "prices", "tariff", "tariffs", "rate", "rates", "revenue",
    "growth", "surge", "claims", "report", "reports", "says", "said",
    "million", "billion", "percent", "industry", "sector", "company",
    "companies", "firm", "firms", "operator", "operators",
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
    "imf funding", "imf disbursement", "imf bailout",
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
    # 休市/放假/停业等例行公告（2026-08-11 加）：交易所与银行的节假日安排对电信
    # 行业和宏观经济都无实质影响，纯日程通知。触发案例：
    # 'PSX, SBP to remain closed on August 14'（独立日休市），靠 sbp 整词匹配混入。
    # 一律用**复合短语**，不能只写 holiday —— 否则会误伤 'holiday package' 这类漫游/
    # 节日资费套餐新闻。
    "remain closed", "remains closed", "to remain shut", "will remain close",
    "public holiday", "bank holiday", "trading holiday", "market holiday",
    "holiday notice", "closure notice", "closed for eid", "holiday schedule",
    "observed as holiday", "declared holiday", "declares holiday",
}


# Unambiguous "this headline is about Pakistan" markers.
_PK_MARKERS = {
    "pakistan", "pakistani", "sbp", "state bank", "islamabad", "karachi",
    "lahore", "peshawar", "quetta", "rawalpindi", "faisalabad",
    "ptcl", "ufone", "jazz", "zong", "jazzworld", "pta", "pmcl", "nrtc", "sco",
}

# Foreign-country markers. The macro terms in _TELECOM_SUB ("central bank",
# "inflation rate", "monetary policy", "interest rate"...) are globally generic,
# and Business Recorder reprints Reuters/AFP wire stories about other countries.
# A headline clearly about a foreign country that never mentions Pakistan is noise
# (e.g. "Thai inflation likely below 2.8% this year, central bank chief says").
_FOREIGN = {
    "thai", "thailand", "india", "delhi", "china", "chinese", "beijing",
    "american", "europe", "european", "britain", "british", "russia", "russian",
    "japan", "korea", "korean", "bangladesh", "sri lanka", "nepal",
    "iran", "afghan", "turkey", "turkish", "egypt", "saudi", "uae", "dubai",
    "qatar", "malaysia", "indonesia", "vietnam", "philippines", "singapore",
    "germany", "german", "france", "french", "italy", "spain", "brazil",
    "mexico", "canada", "australia", "nigeria", "africa",
    # Region/market phrases in Reuters/AFP wire reprints (substring-safe)
    "asian stock", "asian market", "asian share", "wall street", "us inflation",
    "us economy", "us fed", "federal reserve", "us treasury", "us stock",
    # 国际油价基准与产油国组织（2026-08-13 加）：国外油价新闻一律不要。
    # 带这些词又没有强巴基斯坦标识的，一律判为国际行情报道。
    "brent", "wti crude", "opec+", "global oil", "world oil", "international oil",
    "global crude", "global fuel", "oil market",
}

# Foreign markers that are short abbreviations — must be matched as whole words,
# otherwise "us" would hit "business"/"focus", "uk" would hit "sukuk", etc.
# These catch US/UK/EU macro wire stories (e.g. "Asian stocks gain on drop in
# US inflation rate") that _FOREIGN's substring set misses.
_FOREIGN_WB = {"us", "u.s.", "u.s", "uk", "u.k.", "eu", "opec"}

# 地缘政治 → 输入性通胀的传导链（2026-08-11 加）。看板关心的是"外部冲击如何推高
# 巴基斯坦的物价/汇率/进口成本"，不是国际大宗行情本身。这些词全球通用，外电里满天飞，
# 所以命中它们**必须**同时带巴基斯坦标识才算相关——比下面 _FOREIGN 那道闸更严：
# 那道只在标题出现外国词时才要求，这道无条件要求。
# 例：'Oil price surge pushes Pakistan inflation higher' 收；
#     'Middle East conflict sends crude to $100' 不收（没点名巴基斯坦）。
_GEO_MACRO = {
    "oil price", "crude oil", "crude price", "fuel price", "petrol price",
    "diesel price", "energy price", "gas price", "lng price",
    "commodity price", "wheat price", "food price", "food inflation",
    "import bill", "trade deficit", "import cost",
    "geopolitic", "sanctions", "trade war", "tariff war", "import tariff",
    "supply chain", "shipping cost", "freight cost", "freight rate",
    "middle east", "gulf war",
    "rupee depreciation", "rupee devaluation", "currency depreciation",
}

# 弱巴基斯坦标识：只够给 _GEO_MACRO 放行，**不参与** _FOREIGN 的地域豁免。
# 'Rupee depreciation raises import bill' 这类标题不写 Pakistan/SBP，但在巴基斯坦
# 媒体语境里就是 PKR；而印度/斯里兰卡也用 rupee，所以不能升格为正式 _PK_MARKERS
# ——否则 'Indian rupee depreciation hits import bill' 会靠 rupee 骗过地域校验。
_PK_MARKERS_WEAK = {"rupee", "pkr", "psx", "fbr", "nepra", "ogra"}

# 燃油调价的"大幅"门槛（2026-08-13 定）。巴基斯坦油价约 250–280 卢比/升，
# 每升 10 卢比 ≈ 4%，与 5% 的百分比门槛量级一致。见 _is_routine_fuel_price()。
_FUEL_PRICE_HINT = {
    "petrol price", "diesel price", "fuel price", "petroleum price",
    "petrol & diesel", "petrol and diesel", "petrol, diesel",
}
FUEL_BIG_MOVE_RS  = 10.0   # 每升卢比
FUEL_BIG_MOVE_PCT = 5.0    # 或百分比

# "Rs15"/"Rs. 22.50"/"PKR" 这类卢比金额也算弱巴基斯坦标识。必须用正则：
# 裸写 "rs" 做子串会命中 yea-rs、operato-rs，整词匹配又够不着紧跟数字的 "Rs15"。
_PK_WEAK_RE = re.compile(r"\brs\.?\s*\d|\bpkr\b")

# 人事任命（2026-08-11 加）：金融/银行系统的高管任免与通信行业无关
# （触发案例：'Govt Appoints Muhammad Ali Malik as SBP Deputy Governor'，
# 靠 _TELECOM_WB 里的 sbp 混进来）。**只排任命，不排辞职/免职**——央行行长突然
# 去职属于重大宏观变故，与常规履新不是一回事。且标题只要带电信实体就不排，
# 所以 PTA 主席任命、PTCL 高管进 PSTD 理事会这类仍然收得到。
_APPOINTMENT = {
    "appoint", "named as", "takes charge", "takes oath", "sworn in",
    "assumes charge", "assumes office", "assume charge", "assume office",
    "takes over as", "elevated to", "ceo charge", "new deputy governor",
    "new ceo", "new chief executive", "new managing director",
    "board of governors", "board of directors",
}

# 具体商业银行（2026-08-13 加）：看板只要**巴基斯坦经济环境**（SBP 货币政策、
# 利率、通胀、外汇储备、IMF、汇率、财政），不要单家银行的经营动态——高管履新、
# 开分行、发财报、推产品都与电信行业和宏观环境无关。
# 触发案例：'Adil Salahuddin to assume Standard Chartered Pakistan CEO charge
# after SBP clearance'（渣打 CEO 履新，靠 sbp 混入；且因 assume 与 charge 中间
# 隔了四个词，_APPOINTMENT 的短语匹配也够不着）。
# 例外同样是电信实体：'PTCL to acquire Easypaisa from Telenor Microfinance Bank'
# 这类必须保留，见 _is_commercial_bank_news()。
_COMMERCIAL_BANKS = {
    "standard chartered", "habib bank", "united bank", "allied bank",
    "muslim commercial", "bank alfalah", "meezan bank", "faysal bank",
    "askari bank", "js bank", "soneri bank", "summit bank", "silkbank",
    "bank of punjab", "bank of khyber", "sindh bank", "samba bank",
    "dubai islamic bank", "bankislami", "al baraka", "first women bank",
    "khushhali", "u microfinance", "mobilink microfinance",
    "national bank of pakistan", "bank makramah", "zarai taraqiati",
}
# 缩写必须整词匹配：子串会灾难性误伤——"ubl" 命中 p-ubl-ic（public holiday／
# public sector），"abl" 命中 avail-abl-e／t-abl-e／st-abl-e。
_COMMERCIAL_BANKS_WB = {"hbl", "ubl", "mcb", "abl", "bop", "nbp", "jsbl", "bafl"}

# 判断"这条人事新闻是不是电信口的"——命中任一即视为电信相关，不走排除。
_TELECOM_ENTITY = {
    "pta", "telecom", "telco", "jazz", "zong", "ufone", "telenor", "ptcl",
    "moitt", "spectrum", "frequency", "5g", "4g", "sim ", "internet",
    "broadband", "mobile", "fiber", "cellular",
}

# 次要运营商 / 非主要竞争对手（2026-08-11 加）：中小固网、宽带、军方及手机分销商。
# 它们自身的财务重组、股本变动、产品动态不影响行业竞争格局
# （触发案例：'WorldCall Telecom Completes Capital Reduction and Stock Split'）。
# 但"PTA 处罚 WorldCall"这类**监管动作**仍要收——所以只在标题不涉及四大运营商
# 和监管机构时才排除，见 _is_minor_operator_only()。
_MINOR_OPERATORS = {
    "worldcall", "wateen", "nayatel", "transworld", "multinet", "cybernet",
    "stormfiber", "supernet", "circle net", "airlink", "optix",
}
_MINOR_OPERATORS_WB = {"sco", "nrtc"}

# 出现这些就说明新闻涉及主流玩家或监管层，不算"只讲小运营商自己的事"
_MAJOR_PLAYERS = {
    "jazz", "zong", "ufone", "telenor", "ptcl", "jazzworld", "pmcl",
    "pta", "sbp", "moitt", "ccp", "government", "govt", "cabinet",
    "senate", "court", "regulator",
}


def _wb_hit(kw: str, tw: str) -> bool:
    """整词匹配：kw 必须以独立单词出现在已两端补空格的 tw 里。"""
    return " " + kw + " " in tw or tw.startswith(kw + " ") or tw.endswith(" " + kw)


def _is_finance_appointment(t: str) -> bool:
    """非电信口的人事任命 → 丢弃。"""
    if not any(kw in t for kw in _APPOINTMENT):
        return False
    return not any(kw in t for kw in _TELECOM_ENTITY)


def _is_routine_fuel_price(t: str) -> bool:
    """燃油调价：只留大幅调整，例行播报丢弃。

    巴基斯坦每半月调一次油价，'OGRA Announces New Petrol & Diesel Prices for
    Today' 这种例行公告会反复刷屏；但大幅调整确实是通胀先行指标，要留。
    判据是**标题里有没有写出调整幅度**——媒体报大幅调价必然把数字放进标题
    （'hiked by Rs15 per litre'），例行公告则只说"新价格已公布"。
    刻意只认 'by Rs<n>' / '<n>pc' 这类**变动幅度**，不认绝对价格：
    'Petrol price now Rs280 per litre' 里的 280 是价位不是涨幅，仍属例行播报。
    """
    if not any(k in t for k in _FUEL_PRICE_HINT):
        return False
    for pat in (r"by\s+rs\.?\s*(\d+(?:\.\d+)?)",
                r"rs\.?\s*(\d+(?:\.\d+)?)\s*(?:per\s*l(?:it|)re\s*)?"
                r"(?:hike|increase|raise|cut|reduction|drop|decrease)"):
        for m in re.finditer(pat, t):
            if float(m.group(1)) >= FUEL_BIG_MOVE_RS:
                return False
    for m in re.finditer(r"(?:by\s+)?(\d+(?:\.\d+)?)\s*(?:pc\b|%|percent)", t):
        if float(m.group(1)) >= FUEL_BIG_MOVE_PCT:
            return False
    return True


def _is_commercial_bank_news(t: str, tw: str) -> bool:
    """单家商业银行的经营动态 → 丢弃；只保留宏观经济环境类新闻。"""
    hit = any(b in t for b in _COMMERCIAL_BANKS) or any(
        _wb_hit(b, tw) for b in _COMMERCIAL_BANKS_WB)
    if not hit:
        return False
    return not any(kw in t for kw in _TELECOM_ENTITY)


def _is_minor_operator_only(t: str, tw: str) -> bool:
    """只讲次要运营商自己的事（不涉及四大/监管）→ 丢弃。"""
    hit = any(kw in t for kw in _MINOR_OPERATORS) or any(
        _wb_hit(kw, tw) for kw in _MINOR_OPERATORS_WB)
    if not hit:
        return False
    return not any(kw in t for kw in _MAJOR_PLAYERS)


def is_relevant(title: str) -> bool:
    t  = title.lower()
    tw = " " + t + " "
    if any(kw in tw for kw in _EXCLUDE):
        return False
    if _is_finance_appointment(t):
        return False
    if _is_commercial_bank_news(t, tw):
        return False
    if _is_routine_fuel_price(t):
        return False
    if _is_minor_operator_only(t, tw):
        return False
    matched = any(kw in t for kw in _TELECOM_SUB) or any(
        " " + kw + " " in tw or tw.startswith(kw + " ") or tw.endswith(" " + kw)
        for kw in _TELECOM_WB)
    # 地缘/大宗是一条**附加**的通过路径，且必须点名巴基斯坦（见 _GEO_MACRO 注释）。
    # 这里连弱标识（rupee/PKR/PSX/OGRA、以及 "Rs15" 这样的卢比金额）也认，
    # 但弱标识不参与下面的地域豁免。
    pk_any = any(m in t for m in _PK_MARKERS) \
        or any(m in t for m in _PK_MARKERS_WEAK) \
        or _PK_WEAK_RE.search(t) is not None
    geo_ok = any(kw in t for kw in _GEO_MACRO) and pk_any
    # 注意：燃油调价**不设**绕过 pk_any 的放行通道。曾经为了收 'Petrol price up
    # by 9pc' 这种不写国名的标题开过一个口子，但那会顺带放进国际油价新闻
    # （'Global oil prices push petrol up by 12pc' 无任何国名，地域校验也拦不住）。
    # 用户 2026-08-13 明确：国外油价一律不要。宁可漏收本国那种不写标识的写法，
    # 也不放国际行情进来——实际上巴基斯坦媒体报本国油价，标题基本都带 Rs 金额
    # 或 OGRA/Govt，pk_any 里的弱标识已经覆盖。
    if not (matched or geo_ok):
        return False
    # Geography gate: the telecom/macro keywords also match other countries' wire
    # stories. If the headline is clearly about a foreign country and never mentions
    # Pakistan, drop it — otherwise generic macro news (Thai/Indian/US central bank,
    # inflation, rates) slips into a Pakistan-only dashboard.
    foreign = any(kw in t for kw in _FOREIGN) or any(
        " " + kw + " " in tw or tw.startswith(kw + " ") or tw.endswith(" " + kw)
        for kw in _FOREIGN_WB)
    if foreign and not any(m in t for m in _PK_MARKERS):
        return False
    return True


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


def _curl_fetch(url: str, timeout: int = 20, data: bytes = None,
                extra_headers: dict = None, return_raw: bool = False) -> Union[bytes, str]:
    """Use curl subprocess for HTTP(S) requests — avoids Python SSL issues on some networks."""
    cmd = ["curl", "-sS", "--connect-timeout", str(timeout), "-L"]
    # Headers
    all_headers = dict(HEADERS)
    if extra_headers:
        all_headers.update(extra_headers)
    for k, v in all_headers.items():
        cmd += ["-H", f"{k}: {v}"]
    # POST data
    if data is not None:
        cmd += ["-X", "POST", "-d", data.decode("utf-8")]
    cmd.append(url)
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout + 5)
        if result.returncode != 0:
            err = result.stderr.decode("utf-8", errors="replace").strip()[:200]
            raise OSError(f"curl exit {result.returncode}: {err}")
        if return_raw:
            return result.stdout
        charset = "utf-8"
        return result.stdout.decode(charset, errors="replace")
    except Exception as e:
        log(f"  FETCH ERROR [{url}]: {e}")
        return b"" if return_raw else ""


def fetch(url: str, timeout: int = 20) -> str:
    return _curl_fetch(url, timeout=timeout)  # type: ignore[return-value]


_CLOUDFLARE_MARKER = "challenges.cloudflare.com"


def _is_cloudflare(content: str) -> bool:
    """Detect Cloudflare JS challenge / 'Just a moment...' interstitial."""
    return len(content) < 8000 and _CLOUDFLARE_MARKER in content


def fetch_with_browser_fallback(url: str, timeout: int = 20) -> str:
    """Try curl first; if Cloudflare challenge detected, retry with Playwright."""
    content = fetch(url, timeout=timeout)
    if not _is_cloudflare(content):
        return content
    log(f"  Cloudflare challenge detected, retrying with real browser …")
    browser_content = _fetch_page_source_browser(url)
    return browser_content if browser_content else content


def _fetch_page_source_browser(url: str, timeout: int = 30000) -> str:
    """Use Playwright to fetch page content (for sites behind Cloudflare).
    Uses innerText for JSON endpoints (Chrome wraps application/json in <pre>)
    and full page content for XML/HTML pages."""
    global _BROWSER
    try:
        from playwright.sync_api import sync_playwright
        if _BROWSER is None:
            launch_kwargs = {}
            if _proxy_url:
                launch_kwargs["proxy"] = {"server": _proxy_url}
            _BROWSER = sync_playwright().start().chromium.launch(**launch_kwargs)
        page = _BROWSER.new_page(user_agent=HEADERS["User-Agent"])
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            page.wait_for_timeout(8000)
            content = page.content()
            # Chrome wraps JSON responses in <html><body><pre> — extract raw text
            if '<pre>' in content and ('</pre>' in content):
                raw = page.evaluate("() => document.body.innerText")
                if raw.strip():
                    return raw.strip()
            return content
        finally:
            page.close()
    except Exception as e:
        log(f"  Browser page fetch failed ({url}): {e}")
        return ""


_BROWSER = None  # lazily launched, reused across calls, closed by main()


def fetch_article_text_browser(url: str, max_chars: int = 3000) -> str:
    """Playwright fallback for sites that reject plain HTTP requests.
    brecorder.com answers 403 to urllib no matter what headers we send (bot
    protection keyed on TLS fingerprint / JS challenge, not User-Agent — full
    browser headers, the AMP host and third-party proxies were all tried and
    all fail), but loads fine in a real browser, which is why this exists.
    Playwright is already a project dependency (send_daily_digest.py renders
    the digest PNG with it); if it is somehow unavailable we degrade to "" and
    the caller falls back to title-only summarisation as before."""
    global _BROWSER
    try:
        from playwright.sync_api import sync_playwright
        if _BROWSER is None:
            launch_kwargs = {}
            if _proxy_url:
                launch_kwargs["proxy"] = {"server": _proxy_url}
            _BROWSER = sync_playwright().start().chromium.launch(**launch_kwargs)
        page = _BROWSER.new_page(user_agent=HEADERS["User-Agent"])
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            text = re.sub(r"\s+", " ", page.inner_text("body")).strip()
            # Google News RSS links are JS-redirect interstitials: at
            # domcontentloaded the body is still the near-empty bounce page, so
            # a short read means "probably not there yet", not "no content".
            # Wait once and re-read to land on the publisher's actual article.
            if len(text) < 200:
                page.wait_for_timeout(6000)
                text = re.sub(r"\s+", " ", page.inner_text("body")).strip()
        finally:
            page.close()
        return text[:max_chars] if len(text) >= 200 else ""
    except Exception as e:
        log(f"  Browser fetch failed ({url}): {e}")
        return ""


def close_browser() -> None:
    global _BROWSER
    if _BROWSER is not None:
        try:
            _BROWSER.close()
        except Exception:
            pass
        _BROWSER = None


def fetch_article_text(url: str, max_chars: int = 3000) -> str:
    """Best-effort extraction of visible article text from a live page, so
    summarize() can ground its summary in real content instead of guessing
    from the title alone. Tries a plain HTTP GET first (fast, covers most
    sources) and falls back to a real browser for sites that block scripted
    requests. Returns "" only when both routes fail or the page yields
    implausibly little text — callers must treat empty as 'no content
    available, fall back to title-only summarization'."""
    try:
        html = fetch(url, timeout=15)
        if html:
            html = re.sub(r"<(script|style|nav|footer|header)\b[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
            text = re.sub(r"<[^>]+>", " ", html)
            text = html_lib.unescape(text)
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) >= 200:
                return text[:max_chars]
    except Exception as e:
        log(f"  Article content fetch failed ({url}): {e}")
    return fetch_article_text_browser(url, max_chars)


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

        # Filter here like every other fetcher does. Without this, irrelevant
        # headlines reached summarize() and only got dropped by the pre-save
        # is_relevant() rescan — same final cache, but one wasted DeepSeek call
        # each (6 of 10 new items on the 2026-07-19 run).
        if not is_relevant(title):
            continue

        seen.add(article_url)
        items.append({"source": source_label, "title": title, "url": article_url, "date": pub_date})

    # **必须先按日期倒序再截断。** Google News RSS 按*相关性*排序，不是按时间：
    # 2026-08-13 查出 PTA 源自 5 月起再没进过新条目——那次返回 47 条，取前 20 条
    # 的日期全落在 2026-01-08 ~ 05-13，全是早已入库的旧文章，新闻永远排在 20 名
    # 开外被 MAX_ITEMS_PER_SOURCE 切掉。日志里"47 items found"照常打印，缓存却
    # 一条不涨，所以三个月没被发现。SBP 源同理（停在 7-27）。
    items.sort(key=lambda x: x["date"], reverse=True)
    log(f"  Google News [{source_label}]: {len(items)} items found"
        f"（取最新 {min(len(items), MAX_ITEMS_PER_SOURCE)} 条）")
    return items[:MAX_ITEMS_PER_SOURCE]


# Google News 查询的两条硬经验（2026-08-13 查 PTA 源三个月无新条目时得出）：
#   1. **必须带 `when:Nd`**。不带的话 Google 按相关性返回一批历史文章，实测
#      原查询 50 条里最新的一条停在 6-24、8 月以来 0 条；加上 when:14d 后
#      64 条里 60 条是 8 月的。
#   2. **查询词要少**。词堆多了结果集反而急剧缩小："PTA Pakistan telecom
#      regulation spectrum operator when:14d" 只剩 10 条，砍成 "PTA Pakistan
#      telecom when:14d" 有 64 条。宁可放宽召回，噪音交给 is_relevant() 拦。
# 窗口取 14 天而不是 7 天，留出连续数天没跑（出差、代理没挂）的余量。
def fetch_pta() -> list:
    # PTA website is a JS SPA that blocks scrapers; use Google News instead
    return fetch_google_news("PTA Pakistan telecom when:14d", "PTA")


def fetch_sbp() -> list:
    # SBP official site blocks scrapers; use Google News instead
    return fetch_google_news("SBP Pakistan monetary policy when:14d", "SBP")


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
            raw = fetch_with_browser_fallback(url, timeout=15)
            if not raw:
                break
            # If Cloudflare fallback returned but parsing fails, skip
            try:
                posts = json.loads(raw)
            except json.JSONDecodeError:
                log(f"  {source_label} WP API returned non-JSON (likely still blocked)")
                break
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


CONTENT_ENCODED = "{http://purl.org/rss/1.0/modules/content/}encoded"


def rss_body(entry, max_chars: int = 3000) -> str:
    """Article body carried inline in an RSS <item>, stripped of markup.
    Same contract as fetch_article_text(): returns "" when the feed gives us
    too little to ground a summary on, so summarize() falls back to
    title-only mode rather than summarising a one-line teaser as if it were
    the whole story."""
    for tag in (CONTENT_ENCODED, "description"):
        el = entry.find(tag)
        if el is None or not el.text:
            continue
        text = re.sub(r"<[^>]+>", " ", html_lib.unescape(el.text))
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) >= 200:
            return text[:max_chars]
    return ""


def fetch_rss_feed(feed_url: str, source_label: str, display_name: str) -> list:
    """Generic RSS 2.0 <channel><item> reader — used by the general-purpose
    business/finance dailies (Business Recorder, Dawn). These are NOT
    telecom-specific feeds, so is_relevant() filtering matters a lot here: most
    items are unrelated (forex, gold, general markets) and both papers carry
    Reuters/AFP wire copy about other countries, which the geo check in
    is_relevant() is there to reject.

    Both feeds ship the FULL article body in <description>/<content:encoded>,
    which we stash as a transient "article_text" key. This is not an
    optimisation — brecorder.com answers 403 to fetch_article_text() on every
    article page (bot protection; the feed itself stays open), so without this
    every Business Recorder item silently fell through to title-only
    summarisation and DeepSeek invented the details. See main()."""
    log(f"Fetching {display_name} RSS …")
    items = []
    xml_str = fetch_with_browser_fallback(feed_url)
    if not xml_str:
        log(f"  {display_name}: 0 items found")
        return items

    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError as e:
        log(f"  {display_name} XML parse error: {e}")
        return items

    channel = root.find("channel")
    if channel is None:
        log(f"  {display_name}: 0 items found")
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

        items.append({"source": source_label, "title": title, "url": url,
                      "date": pub_date, "article_text": rss_body(entry)})
        if len(items) >= MAX_ITEMS_PER_SOURCE:
            break

    log(f"  {display_name}: {len(items)} items found")
    return items[:MAX_ITEMS_PER_SOURCE]


def fetch_business_recorder() -> list:
    """Business Recorder's Business & Finance RSS — Pakistan's oldest financial
    daily, replaced PhoneWorld (2026-07-02) after a quality complaint: PhoneWorld
    was found to occasionally republish stale/outdated stories under a fresh
    date (e.g. an article claiming the 5G spectrum auction "hadn't happened yet"
    months after it actually concluded in March 2026)."""
    return fetch_rss_feed("https://www.brecorder.com/feeds/business",
                          "BusinessRecorder", "Business Recorder")


def fetch_dawn() -> list:
    """Dawn's Business RSS — Pakistan's paper of record in English (added
    2026-07-19). Editorially the most authoritative of the non-regulator
    sources, but low telecom volume: most of the feed is general macro/markets
    coverage, so expect only a handful of items per run after is_relevant()."""
    return fetch_rss_feed("https://www.dawn.com/feeds/business", "Dawn", "Dawn")


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
            "下面提供了这条新闻的正文节选，请严格根据正文内容撰写摘要和判断重要性，"
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
                    "语言简练专业，不加标题前缀。\n"
                    "重点标注（必做）：在 summary_zh 正文里，把需要强调的短语用中文方括号"
                    "包起来，左括号是 U+3010、右括号是 U+3011。读者主要靠这些标注快速扫读，"
                    "因此两段各必须有 1～2 处，任何一段都不允许一处都没有。\n"
                    "· 第1段标事实：优先具体数字/金额/比例；该段确实没有值得强调的数字时，"
                    "改标最核心的事实结论。\n"
                    "· 第2段标观点：必须标出你的判断性结论本身，不要只标数字。\n"
                    "· 每处6～20字，标短语不标整句，全文合计不超过4处。\n"
                    # 示例刻意用占位符而非真实事实：初版拿一条真实 QoS 新闻做例子，
                    # 模型直接把例句照抄进了那条新闻的摘要里。示例只演示标注位置和
                    # 句式，不提供任何可被搬运的内容。
                    "格式示例（X/Y 为占位符，只示意标注位置，不要照搬其中文字）：\n"
                    "  第1段：……某机构公布数据显示【某指标为X%】，多家企业未达标。\n"
                    "  第2段：……此举短期内【推高相关企业的经营成本】，"
                    "长期看【有利于Y领域的规范化】。\n\n"
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

    try:
        raw = _curl_fetch(
            "https://api.deepseek.com/chat/completions",
            timeout=30, data=payload,
            extra_headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            },
        )
        if not raw:
            return fallback
        result = json.loads(raw)
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
    """Ask DeepSeek to group titles (from the recent DEDUP_LOOKBACK_DAYS window,
    possibly spanning several days) that report the same underlying event with
    different wording (the cheap string-similarity dedup in main() only catches
    near-identical titles). Returns a list of index groups, e.g.
    [[0, 3], [5, 7]]; [] on error or when nothing matches. This is the main
    recall pass but is non-deterministic — mark_duplicates() unions it with the
    deterministic entity_overlap_groups() fallback so an occasional LLM miss
    doesn't let a duplicate through.

    Each entry carries a DEDUP_SUMMARY_CHARS-long excerpt of summary_zh, not just
    the title (2026-07-22): all three dedup layers used to judge on titles alone,
    so two outlets headlining the same story from different angles slipped
    through every one of them. Real case: ProPakistani "Pakistan Gives Telcos New
    Spectrum for Faster 5G Rollout" vs TechJuice "New 5G Rules Push Telecom Firms
    Toward Fiber Expansion" — 18% title similarity (subject, verb and object all
    differ, so judging them distinct was *correct* on the titles), yet the
    summaries are the same E-Band spectrum allocation down to the same figures
    (480 MHz March auction, 17.9% fiberisation, Jazz 22% / Zong 19% / Telenor 16%
    / Ufone 9%). The body text is where sameness is visible, so it has to be in
    the prompt."""
    if len(items) < 2 or not DEEPSEEK_API_KEY:
        return []

    def _entry(i: int, it: dict) -> str:
        line = f"{i}. [{it['source']}] {it['title']}"
        excerpt = (it.get("summary_zh") or "").strip().replace("\n", " ")
        if excerpt:
            line += f"\n   摘要：{excerpt[:DEDUP_SUMMARY_CHARS]}"
        return line

    listing = "\n".join(_entry(i, it) for i, it in enumerate(items))
    payload = json.dumps({
        "model": "deepseek-chat",
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是新闻编辑助手。下面是最近几天抓取到的新闻列表（编号从0开始，可能跨越不同日期），"
                    "每条包含【标题】和【摘要】两行，可能来自不同网站，"
                    "同一新闻事件常被不同网站、在不同日期用不同措辞报道。\n"
                    "【重要】判断时以摘要描述的核心事实为准，标题只作参考——"
                    "不同媒体常给同一条新闻起完全不同角度的标题，只看标题会漏判。"
                    "若两条摘要讲的是同一件事（同一主体+同一动作+同一对象，"
                    "或引用了同一组关键数字/金额/百分比），即为同一事件。\n"
                    "同时注意识别：\n"
                    "· 缩写与全称（如 CPO = Chief People Officer，MoU = 谅解备忘录）；\n"
                    "· 同义动词（Joins / Appointed to / Named to / Elected to 表示同一任命）；\n"
                    "· 主动被动、词序调整、增删修饰语。\n"
                    "示例：「PTCL's Chief People Officer Umer Farid Joins PSTD Board of Governors」"
                    "与「PTCL CPO Umer Farid Appointed to PSTD Board of Governors」是同一事件；"
                    "「IHC Clears Telenor's Merger Into Ufone」与「IHC Approves Telenor-Ufone Merger」是同一事件；"
                    "「Pakistan Gives Telcos New Spectrum for Faster 5G Rollout」"
                    "与「New 5G Rules Push Telecom Firms Toward Fiber Expansion」标题看似无关，"
                    "但摘要都是政府分配E-Band频谱、且引用同一组光纤化率数字，属同一事件。\n"
                    "但下列情况【不是】同一事件，必须全部保留：\n"
                    "· 同一话题下的不同角度（如合并后的『资费上涨』与『员工裁员』）；\n"
                    "· 一条是对另一条报道的反驳、澄清、更正或官方回应——"
                    "例如「Mobile phone imports top Rs520bn in FY26」（媒体报道进口额大增）"
                    "与「Customs Rejects Claims of Surge in Finished Mobile Phone Imports」"
                    "（海关出面驳斥该报道、称统计口径被误读）虽然围绕同一组数据，"
                    "但后者是事件的新进展和对立观点，是最有价值的信息，绝不能当作重复删掉；\n"
                    "· 同一指标在不同时间点的更新（如上月与本月的储备数据）。\n"
                    "判断要点：若两条的核心事实一致、只是措辞不同 → 重复；"
                    "若其中一条提供了新的立场、否定、进展或后续动作 → 不是重复。\n"
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

    try:
        raw = _curl_fetch(
            "https://api.deepseek.com/chat/completions",
            timeout=30, data=payload,
            extra_headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            },
        )
        if not raw:
            return []
        result = json.loads(raw)
        content = json.loads(result["choices"][0]["message"]["content"])
        groups = content.get("duplicate_groups", [])
    except Exception as e:
        log(f"  DeepSeek dedup error: {e}")
        return []

    return _split_importance_mismatch_groups(
        _split_disconnected_groups(
            _split_rebuttal_groups(groups, items), items), items)


# Words marking a story as *disputing* another one rather than retelling it.
# Matched against the headline and the opening of the summary only — a rebuttal
# announces itself there. Scanning the whole summary produced false positives on
# ordinary reporting: "PTA 要求运营商采取纠正措施" (corrective measures) and
# "议员引用帖子反驳" (someone inside the story disputing someone else) both
# tripped it, neither being a rebuttal *of another article*.
_REBUTTAL_MARKERS_EN = (
    "reject", "denies", "denied", "deny", "refute", "rebut", "dismisses",
    "disputes", "clarifies", "clarification", "debunk", "no truth", "not true",
)
_REBUTTAL_MARKERS_ZH = ("驳斥", "否认", "澄清", "辟谣", "不实", "误读", "误解")
REBUTTAL_LEAD_CHARS = 60


def _is_rebuttal(item: dict) -> bool:
    title = (item.get("title") or "").lower()
    if any(m in title for m in _REBUTTAL_MARKERS_EN):
        return True
    lead = (item.get("summary_zh") or "")[:REBUTTAL_LEAD_CHARS]
    return any(m in lead for m in _REBUTTAL_MARKERS_ZH)


def _split_rebuttal_groups(groups: list, items: list) -> list:
    """Drop LLM groups that mix a report with a rebuttal of that report.

    Feeding summaries to the model (see llm_dedup_groups) made it much better at
    spotting reworded duplicates, but it also started merging a story with the
    story *denying* it — both summaries cite the same figures, so on content
    alone they look identical. Real case (2026-07-22): Dawn "Mobile phone imports
    top Rs520bn in FY26" merged with ProPakistani "Customs Rejects Claims of
    Surge in Finished Mobile Phone Imports", where Customs is disputing exactly
    that report. Prompt wording did not fix it — the model returned the same
    merge on repeated runs at temperature 0 — so the rule is enforced in code.

    A group is only split when it *mixes* the two kinds: if every member is a
    rebuttal, several outlets are covering the same denial and merging is right.
    Losing the dissenting take is far worse than showing one extra item, so this
    errs toward keeping both."""
    out = []
    for grp in groups:
        idx = [i for i in grp if isinstance(i, int) and 0 <= i < len(items)]
        if len(idx) < 2:
            continue
        flags = [_is_rebuttal(items[i]) for i in idx]
        if any(flags) and not all(flags):
            kept = [items[i].get("title", "")[:60] for i in idx]
            log(f"  Dedup: kept report+rebuttal apart — {' | '.join(kept)}")
            continue
        out.append(idx)
    return out


def _split_importance_mismatch_groups(groups: list, items: list) -> list:
    """把重要性不一致的 LLM 合并组拆开——只在组里混有"高"时才拆。

    同一事件的两篇报道，分量应该是一样的：`summarize()` 对同一件事给出的
    重要性判定高度一致（实测 PTA 罚 Zong 那组两家媒体都判"中"，DIRBS 升级
    跨天那组也都是"中"）。所以组内重要性不一致，本身就是"这压根不是同一件事"
    的信号。

    真实事故（2026-08-13）：Dawn《Regional war drives global food inflation,
    poses risks for Pakistan》（判"高"）被并进前一天 Dawn《SBP warns of price
    spirals due to geopolitical developments in Middle East》（判"中"）。两条
    都在讲"地缘政治推高物价"，喂了摘要的 LLM 看内容确实近似，但一条是 SBP
    货币政策报告、一条是战争对全球粮价的专题分析，是不同事件；结果当天分量
    最重的一条被静默丢掉，日报里也跟着少了。

    **必须两个信号同时成立才拆**：重要性不一致 **且** 组内没有任何两条共享标题
    实体词。单看任一个都会误判：
      · 只看重要性——首版就是这样，当场误拆了两组真同事件报道：
        《SBP Tightens Oversight of Rs88 Billion Export Subsidies》(高) 与
        《SBP Sets New Rules To Strictly Monitor Rs. 88 Billion Export Subsidies》(中)
        讲的是同一件事，只是 summarize() 给的分量不同。同事件报道的重要性
        **并不总是一致**，从一个案例推出的判据在别处立刻崩掉。
      · 只看共同实体——会误伤本文件注释里记录在案的正确合并：ProPakistani
        《Pakistan Gives Telcos New Spectrum for Faster 5G Rollout》与 TechJuice
        《New 5G Rules Push Telecom Firms Toward Fiber Expansion》零共同实体词，
        却确实是同一件事，那正是 LLM 层存在的意义。
    两个独立信号都指向"不是同一事件"时才动手，误拆概率低得多。

    与 _split_rebuttal_groups 同一取舍：丢掉一条重要新闻的代价，远大于多展示
    一条重复的。"""
    out = []
    for grp in groups:
        idx = [i for i in grp if isinstance(i, int) and 0 <= i < len(items)]
        if len(idx) < 2:
            continue
        imps = {(items[i].get("importance") or "中") for i in idx}
        if "高" in imps and len(imps) > 1 and not _group_shares_entity(idx, items):
            kept = [f"{items[i].get('importance') or '中'}:{items[i].get('title','')[:44]}"
                    for i in idx]
            log(f"  Dedup: 重要性不一致且标题无共同实体，判为不同事件保留 — {' | '.join(kept)}")
            continue
        out.append(idx)
    return out


def _group_shares_entity(idx: list, items: list) -> bool:
    """组内是否存在任意两条共享标题实体词（`_title_tokens` 已剔除停用词）。"""
    toks = [_title_tokens(items[i].get("title", "")) for i in idx]
    return any(toks[a] & toks[b]
               for a in range(len(toks)) for b in range(a + 1, len(toks)))


def _dedup_entity_tokens(item: dict) -> set:
    """标题 + 摘要前 DEDUP_SUMMARY_CHARS 字的实体词。

    摘要是必需的：同一事件被不同媒体改写后，标题可能一个共同词都不剩
    （'PTA imposes Rs77.8mn fine on CM Pak' vs 'Zong slapped with Rs77Million
    penalty over Illegal BVS Device Operation'），但摘要里的金额、机构名对得上。
    中文摘要不做分词，`_title_tokens` 的 [a-z0-9]+ 正好把数字和英文专名捞出来
    （"7780万卢比" → 7780），足够判定同一性。"""
    return _title_tokens(item.get("title", "")) | _title_tokens(
        (item.get("summary_zh") or "")[:DEDUP_SUMMARY_CHARS])


# 本看板几乎每条新闻都会出现的机构/主体词。它们不携带"同一事件"的信息，
# 靠它们连边会把整天的新闻串成一个巨型连通块。（不放进 _DEDUP_STOP，那张表
# 服务于确定性去重层，动它会改变已验证过的合并行为。）
_LINK_GENERIC = {"pta", "sbp", "ptcl", "psx", "ogra", "nepra", "govt",
                 "government", "authority", "regulator"}


def _strong_link(a: set, b: set) -> bool:
    """两条新闻是否强相关：剔除通用主体词后还有共享实体，就算。

    早先的写法是"共享 ≥2 个词或含数字词"，把《Telcos Could Increase Data
    Charges for Survival》从数据资费那组拆了出去——它与同组另两条只共享
    `arpu` 一个词，但 arpu 恰恰是指向性很强的专业术语，不该按"只有一个词"
    否掉。真正没有信息量的是 `pta`/`sbp` 这类主体词：事故组里"取消手机税"
    与三条罚款新闻的全部交集就是一个 `pta`。所以按**词的分量**过滤，而不是
    数个数。"""
    return bool((a & b) - _LINK_GENERIC)


def _split_disconnected_groups(groups: list, items: list) -> list:
    """把 LLM 合并组按"强相关"连通性拆成若干子组。

    候选变多以后（2026-08-13 接入 PTA/SBP 两个 Google News 源，单日候选从个位
    数涨到 19 条），LLM 开始把不相干的新闻并进同一组。真实事故：
      保留 《Pakistan Government Considers Abolishing Mobile Phone Taxes》
      丢弃 《PTA imposes Rs77.8mn fine on CM Pak for SIM geo-fencing breach》
      丢弃 《PTA Imposes Rs. 77.8 Million Fine on China Mobile Pakistan》
      丢弃 《Zong slapped with Rs77Million penalty over Illegal BVS Device Operation》
    "政府考虑取消手机税"和"Zong 被罚 7780 万卢比"是毫不相干的两件事，结果当天
    与本公司直接相关的处罚新闻整个从看板消失。

    组内按 _strong_link 建图取连通分量：上例拆成 {取消手机税} 和 {三条罚款}，
    罚款仍正确合并成一条展示。取舍与 _split_rebuttal_groups 一致——拆错了不过是
    多展示一条重复，不拆则可能静默丢掉一条重要新闻。"""
    out = []
    for grp in groups:
        idx = [i for i in grp if isinstance(i, int) and 0 <= i < len(items)]
        if len(idx) < 2:
            continue
        toks = {i: _dedup_entity_tokens(items[i]) for i in idx}
        parent = {i: i for i in idx}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for a in range(len(idx)):
            for b in range(a + 1, len(idx)):
                i, j = idx[a], idx[b]
                if _strong_link(toks[i], toks[j]):
                    ri, rj = find(i), find(j)
                    if ri != rj:
                        parent[ri] = rj

        comps: dict = {}
        for i in idx:
            comps.setdefault(find(i), []).append(i)
        if len(comps) > 1:
            log(f"  Dedup: 组内实体不连通，拆成 {len(comps)} 组 — "
                + " ‖ ".join("/".join(items[i].get("title", "")[:34] for i in c)
                             for c in comps.values()))
        out.extend(sorted(c) for c in comps.values() if len(c) >= 2)
    return out


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
    cache: across the last DEDUP_LOOKBACK_DAYS days pooled together (so a
    duplicate straddling two days is caught, not just same-day repeats), tag
    every non-best copy of an entity-overlap group with `dup_of` (the URL of the
    kept item); display skips tagged items. Persisting the decision (vs
    recomputing every run) is what stops an already-deduped story from
    resurfacing.

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

    # Pool the whole DEDUP_LOOKBACK_DAYS window into one set (this previously ran
    # one day at a time, so it could only catch same-day repeats). Pooling makes
    # the deterministic pass cross-day: an event first reported on an earlier day
    # and reworded by another outlet on a later day collapses onto the earlier
    # copy. df is computed over the window, so a topic word shared across many
    # days becomes high-frequency and drops out of the rare-token test — the
    # >= ENTITY_OVERLAP_MIN_RARE rare-shared-token bar stays exactly as
    # conservative as the old same-day pass and still never merges different
    # developments of one rolling story.
    active = [it for it in cache
              if it.get("date", "") >= cutoff and it.get("summary_zh", "").strip()
              and not it.get("dup_of")]

    total_tagged = 0
    if len(active) >= 2:
        # Earliest date first so a cross-day duplicate keeps the copy already
        # shown on the earlier day; within one date, best (importance, source).
        active.sort(key=lambda x: (
            x.get("date", ""),
            IMPORTANCE_PRIORITY.get(x.get("importance", "中"), 1),
            SOURCE_PRIORITY.get(x.get("source", ""), 99),
        ))
        groups = entity_overlap_groups(active)

        # Union all groups into connected components; keep the lowest index
        # (earliest date, then best-ranked).
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

    fetchers = [fetch_pta, fetch_sbp, fetch_propakistani, fetch_dawn,
                fetch_business_recorder, fetch_techjuice]
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
        # pop, not get: the RSS body is only needed for this one summarize()
        # call and must not be persisted into news_cache.json. Sources whose
        # feed carries the full text (Dawn, Business Recorder) supply it here;
        # everyone else falls back to scraping the live page.
        article_text = item.pop("article_text", "") or fetch_article_text(item["url"])
        if not article_text:
            log(f"    ! no article text — title-only summary (may be unreliable)")
        result = summarize(item["title"], item["url"], article_text)
        item["summary_zh"] = result["summary_zh"]
        item["importance"] = result["importance"]
        time.sleep(0.5)

    # Prepend new items and save
    cache = new_items + cache
    # 过滤规则**只作用于新抓取的条目**，不回溯清洗历史缓存（2026-08-13 用户明确）。
    # 以前这里每次运行都拿最新规则把整份 cache 重筛一遍（"历史残留自愈清除"），
    # 副作用是：调一次关键词就可能悄悄抹掉若干条早已展示过的旧新闻，而且改规则
    # 必须跑一整轮抓取才能生效。现在改成默认不动历史，需要按新规则清理旧数据时
    # 显式加 --reclean（见文件末尾 argv 处理）。
    if RECLEAN_CACHE:
        before = len(cache)
        cache = [i for i in cache if is_relevant(i.get("title", ""))]
        log(f"  --reclean: 按当前规则回扫历史，剔除 {before - len(cache)} 条")
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

    # Run the LLM same-event dedup once over the whole recent window rather than
    # one day at a time, so it also catches a story reworded by a different
    # outlet the *next day* — the common cross-day duplicate (e.g. TechJuice's
    # "PTA Fines Jazz, Zong, Ufone and Telenor Rs740 Million" one day and
    # BusinessRecorder's "PTA imposes Rs740m penalties on four cellular mobile
    # operators" the next). Those two share < ENTITY_OVERLAP_MIN_RARE rare tokens,
    # so the deterministic entity pass can't merge them; only the LLM can. Kept
    # non-persisted on purpose: an occasional LLM over-merge only affects this
    # one run's display and self-corrects next run, so it can never permanently
    # drop a distinct story (same rationale as mark_duplicates). Sorted earliest
    # first so the copy already shown on the earlier day is the one kept.
    _llm_drop_urls: set = set()
    _recent = [it for _d0 in _by_day for it in _by_day[_d0] if _d0 >= dedup_cutoff]
    if len(_recent) > 1:
        _recent.sort(key=lambda x: (
            x.get("date", ""),
            IMPORTANCE_PRIORITY.get(x.get("importance", "中"), 1),
            SOURCE_PRIORITY.get(x.get("source", ""), 99),
        ))
        for _grp in llm_dedup_groups(_recent):
            _valid = sorted(i for i in _grp if isinstance(i, int) and 0 <= i < len(_recent))
            for _i in _valid[1:]:  # keep earliest-day (lowest index), drop the rest
                _llm_drop_urls.add(_recent[_i].get("url", ""))

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

        # Drop items the cross-day LLM pass (computed once over the whole recent
        # window, above) flagged as same-event repeats of an earlier-day story.
        if _llm_drop_urls:
            deduped = [it for it in deduped if it.get("url", "") not in _llm_drop_urls]

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

    close_browser()
    log("News update complete")
    log("=" * 50)


if __name__ == "__main__":
    import sys
    # --reclean：按当前过滤规则回扫整份历史缓存并剔除不合规条目。
    # 平时不要用——改规则默认只影响以后抓到的新闻（见 main() 里的说明）。
    RECLEAN_CACHE = "--reclean" in sys.argv
    main()
