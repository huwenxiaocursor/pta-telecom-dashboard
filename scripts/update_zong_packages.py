#!/usr/bin/env python3
"""
Zong 套餐清单自动更新脚本。

每两个月由 GitHub Actions 触发（见 .github/workflows/update.yml 的 update-zong job）。
从 zong.com.pk 的预付费/后付费页面抓取**全量**套餐（含国际漫游/IDD、Apna Shehr/Area Play
地区套餐），按 slug 去重，用确定性规则把英文套餐内容翻译成中文、并归类，然后替换
zong_packages_index.html 中 sentinel 之间的 `const PLANS = [...]` 数组与采集日期。

设计取舍（见 CLAUDE.md「Zong 套餐清单自动化」）：
- 纯规则翻译/分类，不调用 LLM——套餐内容词汇表很小且固定（GB/Zong Mins/Off-net Mins/
  SMS/Int Mins/All Net Mins），确定性映射即可，避免 LLM 脑补价格或内容。
- 每次全量刷新，不保留历史（页面是当前快照，历史无回溯价值）；靠 git diff 判断是否有变化。
- 抓取失败或解析到的套餐数异常偏少时**抛错中止**，不写入半截数据覆盖好页面。

无第三方依赖，仅用标准库（与 update_pta_dashboard.py 一致）。
"""
import re
import sys
import pathlib
import datetime
import urllib.request

BASE_DIR = pathlib.Path(__file__).resolve().parent
HTML_FILE = BASE_DIR.parent / "zong_packages_index.html"
LOG_FILE = BASE_DIR / "zong_update_log.txt"

PREPAID_URL = "https://www.zong.com.pk/prepaid"
POSTPAID_URL = "https://www.zong.com.pk/postpaid"

START = "// ===AUTO-ZONG-START==="
END = "// ===AUTO-ZONG-END==="

# 抓到的去重套餐数低于这个阈值就认为页面结构变了/抓取残缺，抛错中止（正常约 500 个）。
MIN_EXPECTED = 200

CN_MONTHS = ["", "1月", "2月", "3月", "4月", "5月", "6月",
             "7月", "8月", "9月", "10月", "11月", "12月"]

# 分类用：国家/地区关键词，命中即判为国际漫游
COUNTRIES = (r'thailand|malaysia|germany|hong kong|azerbaijan|saudi|turkey|qatar|iraq|oman|france|'
             r'\buk\b|usa|uae|dubai|china|canada|italy|spain|singapore|indonesia|sri lanka|bangladesh|'
             r'nepal|kuwait|bahrain|jordan|egypt|iran|afghanistan|greece|netherlands|belgium|australia|'
             r'japan|korea|russia|switzerland|austria|sweden|norway|denmark|poland|maldives|mauritius|'
             r'continental america|continental asia|continental europe')


def log(msg):
    ts = datetime.datetime.now().isoformat(timespec='seconds')
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + "\n")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read().decode('utf-8', errors='ignore')


def parse(html, ptype):
    """把一张页面里的套餐卡解析成 dict 列表；服务端渲染的 <article class="card single_bundle">。"""
    parts = re.split(r'<article class="card single_bundle', html)[1:]
    rows = []
    for c in parts:
        c = c[:c.find('</article>')]
        slugm = re.search(r'/(?:prepaid|postpaid)/([a-z0-9\-]+)"', c)
        if not slugm:
            continue
        slug = slugm.group(1)
        namem = re.search(r'/(?:prepaid|postpaid)/[a-z0-9\-]+">\s*([^<]+?)\s*</a>', c)
        name = re.sub(r'\s+', ' ', namem.group(1)).strip() if namem else slug
        valm = re.search(r'<small[^>]*>\s*([A-Za-z0-9 ]+?)\s*</small>', c)
        val = valm.group(1).strip() if valm else ''
        pricem = re.search(r'PKR\.?\s*([\d,]+)(?:\.\d+)?', c)
        price = pricem.group(1).replace(',', '') if pricem else ''
        feats = []
        for sc in re.findall(r'<div class="specs_col">(.*?)</div>', c, re.S):
            t = re.sub(r'<[^>]+>', ' ', sc)
            t = re.sub(r'\s+', ' ', t).strip()
            if t and t not in feats:
                feats.append(t)
        rows.append(dict(slug=slug, name=name, val=val, price=price, feats=feats, ptype=ptype))
    # 同一 slug 常在「热门」和分栏里重复出现，按 slug 去重（保留第一次）
    seen = {}
    for r in rows:
        seen.setdefault(r['slug'], r)
    return list(seen.values())


def tr_feat(f):
    """英文套餐内容 → 中文；无法识别的原样保留（不编造）。"""
    s = f.strip()
    low = s.lower()
    m = re.match(r'^([\d.]+)\s*(gb|mb)\b(.*)$', s, re.I)
    if m:
        num, unit, rest = m.group(1), m.group(2).upper(), m.group(3).strip()
        q = ''
        qm = re.search(r'\(([^)]+)\)', rest)
        if qm:
            inner = qm.group(1).strip()
            if inner.lower() == 'social':
                q = ' 社交'
            elif inner.lower() not in ('internet', 'total data'):
                q = ' ' + inner
        appm = re.search(r'whatsapp|youtube|tiktok|imo', rest, re.I)
        if appm and not q:
            q = ' ' + appm.group(0)
        return re.sub(r'\s+', ' ', f'{num}{unit}{q} 流量').strip()
    if 'unlimited' in low and 'data' in low:
        return '无限 流量'
    if 'unlimited' in low and 'zong' in low:
        return '无限 Zong 分钟'
    if 'unlimited' in low and 'min' in low:
        return '无限 全网分钟'
    m = re.match(r'^([\d.]+)\s*zong\s*min', low)
    if m:
        return f'{m.group(1)} Zong 分钟'
    m = re.match(r'^([\d.]+)\s*off[- ]?net\s*min', low)
    if m:
        return f'{m.group(1)} 跨网分钟'
    m = re.match(r'^([\d.]+)\s*all\s*net\s*min', low)
    if m:
        return f'{m.group(1)} 全网分钟'
    m = re.match(r'^([\d.]+)\s*int\.?\s*min', low)
    if m:
        return f'{m.group(1)} 国际分钟'
    m = re.match(r'^([\d.]+)\s*min', low)
    if m:
        return f'{m.group(1)} 分钟'
    m = re.match(r'^([\d.]+)\s*sms', low)
    if m:
        return f'{m.group(1)} 条短信'
    if 'mca' in low:
        return '免费 MCA'
    return s


def tr_val(v, ptype):
    if not v:
        return 'Monthly' if ptype == 'postpaid' else ''
    return re.sub(r'\bHour[s]?\b', '小时', v).strip()


def category(r):
    """把套餐归入 SEC 的某一类；顺序敏感（先判漫游/地区，再判国内套餐构成）。"""
    n = r['name'].lower()
    fl = ' '.join(r['feats']).lower()
    if re.search(r'\broaming\b|\bir\b|\bidd\b|international|data ir|voice ir|\bir[- ]', n) or re.search(COUNTRIES, n):
        return 'roaming'
    if 'apna shehr' in n or 'area' in n or re.search(r'kashmir|azad jammu|gilgit|baltistan', n):
        return 'area'
    if re.search(r'whatsapp|youtube|tiktok|facebook|pubg|google maps|imo|social|instagram', n):
        return 'app'
    if re.search(r'zong tv|bajao|caller|rbt|securet|ozgpt|bussu|utility', n):
        return 'vas'
    has_data = bool(re.search(r'\d+\s*gb|\d+\s*mb|internet|total data|unlimited data', fl))
    has_voice = bool(re.search(r'min|sms', fl))
    if has_data and not has_voice:
        return 'data'
    if has_voice and not has_data:
        return 'voice'
    return 'hybrid'


def emit(r):
    t = r['ptype']
    c = category(r)
    v = tr_val(r['val'], t)
    feats = [tr_feat(x) for x in r['feats']]
    name = r['name'].replace('\\', '').replace('"', '\\"')
    fj = ','.join('"%s"' % x for x in feats)
    return '  {n:"%s",t:"%s",c:"%s",v:"%s",p:"%s",f:[%s]},' % (name, t, c, v, r['price'], fj)


def build_block(rows):
    lines = [emit(r) for r in rows]
    body = '\n'.join(lines)
    return f"{START}  （此块由 scripts/update_zong_packages.py 自动生成，勿手动改）\nconst PLANS = [\n{body}\n];\n{END}"


def main():
    log("开始抓取 Zong 套餐 …")
    try:
        pre = parse(fetch(PREPAID_URL), 'prepaid')
        post = parse(fetch(POSTPAID_URL), 'postpaid')
    except Exception as e:
        log(f"抓取失败，保留原页面不动：{e}")
        sys.exit(1)

    rows = post + pre
    if len(rows) < MIN_EXPECTED:
        log(f"解析到的套餐数异常偏少（{len(rows)} < {MIN_EXPECTED}），疑似页面结构变化，"
            f"中止并保留原页面。请人工检查 Zong 官网 HTML 结构。")
        sys.exit(1)

    import collections
    dist = collections.Counter(category(r) for r in rows)
    log(f"抓取成功：预付费 {len(pre)} + 后付费 {len(post)} = {len(rows)} 个（去重后）")
    log(f"分类分布：{dict(dist)}")

    html = HTML_FILE.read_text(encoding='utf-8')

    block = build_block(rows)
    m = re.search(re.escape(START) + r'.*?' + re.escape(END), html, re.DOTALL)
    if not m:
        log("HTML 中找不到 AUTO-ZONG sentinel，需人工检查页面")
        sys.exit(1)
    html = html[:m.start()] + block + html[m.end():]

    today = datetime.date.today()
    date_cn = f"{today.year}年{CN_MONTHS[today.month]}"
    html = re.sub(r'(<!--ZONG-DATE-START-->).*?(<!--ZONG-DATE-END-->)',
                  lambda mm: mm.group(1) + date_cn + mm.group(2), html, flags=re.DOTALL)

    HTML_FILE.write_text(html, encoding='utf-8')
    log(f"已写入 {HTML_FILE.name}，采集日期标注为 {date_cn}，共 {len(rows)} 个套餐。")


if __name__ == '__main__':
    main()
