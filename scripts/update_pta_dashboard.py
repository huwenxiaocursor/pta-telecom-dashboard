#!/usr/bin/env python3
import os
import re
import json
import sys
import shutil
import pathlib
import datetime
import urllib.request

SUBSCRIBERS_URL = "https://www.pta.gov.pk/category/telecom-indicators/164"
QOS_LIST_URL = "https://www.pta.gov.pk/category/qos-survey-959959384-2023-05-30"

BASE_DIR = pathlib.Path(__file__).resolve().parent
HTML_FILE = BASE_DIR.parent / "index.html"
LOG_FILE = BASE_DIR / "update_log.txt"
KNOWN_QOS_FILE = BASE_DIR / "known_qos_pdfs.json"
QOS_ALERT_FILE = BASE_DIR / "qos_update_needed.txt"
HISTORY_FILE = BASE_DIR / "history_monthly.json"

MONTH_MAP = {'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
             'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12}

OPERATORS = ['Jazz', 'Ufone', 'Zong', 'Telenor', 'SCO']

# 年度指标抓取配置：(category_id, chart_id, 需要的series名称列表)
ANNUAL_SOURCES = [
    (168, 'revenues-chart',                         ['CMO', 'FLL / WLL', 'LDI', 'TTP/TIP', 'CVAS']),
    (169, 'investments-chart',                       ['CMO', 'LDI', 'TTP/TIP', 'FLL/CVAS']),
    (170, 'foreign-direct-investments-chart',        ['Inflow', 'Net FDI']),
    (171, 'mobile-device-manufacturing-chart',       ['Smart Phones', '2G']),
    (173, 'annual-cellular-mobile-cell-sites-chart', ['2G', '3G', '4G']),
    (174, 'mobile-arpu-per-month-during-year-chart', ['ARPU']),
]

# 月度额外指标：(history_key, category_id, chart_id, series名称列表)
MONTHLY_EXTRA_CHARTS = [
    ('dataUsage',   164, 'monthly-mobile-data-usage-gbs-chart',  OPERATORS + ['Total']),
    ('ngmsSubs',    164, 'monthly-ngms-subscribers-chart',        OPERATORS + ['Total']),
    ('broadband',   164, 'monthly-broadband-subscribers-chart',   ['Total', 'FTTH', 'Mobile BB']),
    ('teledensity', 165, 'monthly-teledensity-chart',             ['Total']),
]


def log(msg):
    ts = datetime.datetime.now().isoformat(timespec='seconds')
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + "\n")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode('utf-8', errors='ignore')


def to_iso_month(label):
    mon, yy = label.split('-')
    year = 2000 + int(yy)
    return f"{year:04d}-{MONTH_MAP[mon]:02d}"


def extract_chart(html, chart_id):
    """通用 Highcharts 数据提取，返回 (categories_list, {name: [values]}) 或 (None, None)"""
    anchor = html.find(f'Highcharts.chart("{chart_id}"')
    if anchor == -1:
        return None, None
    window = html[anchor:anchor + 25000]
    cat_m = re.search(r'"categories":(\[[^\]]*\])', window)
    series_m = re.search(r'series:\s*(\[.*?\}])', window, re.DOTALL)
    if not cat_m or not series_m:
        return None, None
    categories = json.loads(cat_m.group(1))
    data_matches = re.findall(r'"name":"([^"]+)".*?"data":(\[[^\]]+\])', series_m.group(1), re.DOTALL)
    series = {name: json.loads(data) for name, data in data_matches}
    return categories, series


def load_history():
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding='utf-8'))
    return {}


def save_history(history):
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding='utf-8')


def merge_monthly_into_history(history, key, month_labels, series_dict):
    """将月份标签和对应数据合并入 history[key]，已有月份的已有字段不覆盖"""
    if key not in history:
        history[key] = {}
    for i, label in enumerate(month_labels):
        try:
            iso = to_iso_month(label)
        except Exception:
            continue
        if iso not in history[key]:
            history[key][iso] = {}
        for sname, values in series_dict.items():
            if sname not in history[key][iso]:
                history[key][iso][sname] = values[i]


def rebuild_months_from_history(history, n_months=13):
    """从历史记录重建月度用户数数组（最近n_months个月，按时间排序）"""
    cell_hist = history.get('cellularSubs', {})
    all_months = sorted(cell_hist.keys())
    recent = all_months[-n_months:]
    subs_out = {op: [cell_hist[m][op] for m in recent] for op in OPERATORS if op in cell_hist.get(recent[0], {})}
    return recent, subs_out


def build_yoy_arrays(history, key, series_names, years=(2025, 2026)):
    """从 history 构建 {year: {sname: [12个值/null]}}"""
    result = {}
    for year in years:
        result[year] = {}
        for sname in series_names:
            arr = []
            for m in range(1, 13):
                val = history.get(key, {}).get(f'{year}-{m:02d}', {}).get(sname, None)
                arr.append(val)
            result[year][sname] = arr
    return result


def fetch_subscriber_data():
    html = fetch(SUBSCRIBERS_URL)
    anchor = html.find('Highcharts.chart("monthly-cellular-subscribers-chart"')
    if anchor == -1:
        raise RuntimeError("找不到 monthly-cellular-subscribers-chart 锚点，PTA页面结构可能已变化，需人工检查")
    window = html[anchor:anchor + 20000]

    cat_m = re.search(r'"categories":(\[[^\]]*\])', window)
    series_m = re.search(r'series:\s*(\[{"name":"Jazz".*?\}])', window, re.DOTALL)
    if not cat_m or not series_m:
        raise RuntimeError("未能在锚点附近解析出 categories 或 series，需人工检查PTA页面")

    categories = json.loads(cat_m.group(1))
    series = json.loads(series_m.group(1))

    raw_months = [to_iso_month(c) for c in categories]
    raw_subs = {s['name']: s['data'] for s in series if s['name'] in OPERATORS}
    totals_reported = next((s['data'] for s in series if s['name'] == 'Total'), None)

    missing = [op for op in OPERATORS if op not in raw_subs]
    if missing:
        raise RuntimeError(f"缺少运营商数据：{missing}，需人工检查")

    # 按月份去重后验证（PTA可能用交错YoY格式，导致categories非顺序）
    seen = {}
    for i, iso in enumerate(raw_months):
        seen[iso] = {op: raw_subs[op][i] for op in OPERATORS}

    for iso, vals in seen.items():
        s = sum(vals[op] for op in OPERATORS)
        if totals_reported:
            idx = raw_months.index(iso)
            if abs(s - totals_reported[idx]) > 2000:
                raise RuntimeError(
                    f"{iso} 用户数求和({s})与PTA披露Total({totals_reported[idx]})不一致，已中止更新"
                )

    # 保留原始对齐数据（供 merge_monthly_into_history 使用）
    # 同时返回排序后数据（供 rebuild_months_from_history / HTML 使用）
    raw_subs_aligned = {op: [seen.get(m, {}).get(op) for m in raw_months] for op in OPERATORS}
    return raw_months, raw_subs_aligned, categories, html


def fetch_annual_metrics():
    """抓取6类年度指标，返回 {chart_id: {'years': [...], 'series': {...}}}"""
    results = {}
    for cat_id, chart_id, expected_keys in ANNUAL_SOURCES:
        try:
            html = fetch(f'https://www.pta.gov.pk/category/telecom-indicators/{cat_id}')
            cats, series = extract_chart(html, chart_id)
            if cats is None:
                log(f"警告：{chart_id} 未找到数据，跳过")
                continue

            if chart_id == 'mobile-device-manufacturing-chart':
                # 排除 'Jan-Apr XX' 类不完整年份
                valid = [(i, c) for i, c in enumerate(cats) if c[:1].isdigit()]
                keep_idx = [x[0] for x in valid[-5:]]
                cats = [x[1] for x in valid[-5:]]
                series = {k: [v[i] for i in keep_idx] for k, v in series.items()}
            else:
                n = min(5, len(cats))
                cats = cats[-n:]
                series = {k: v[-n:] for k, v in series.items()}

            results[chart_id] = {
                'years': cats,
                'series': {k: v for k, v in series.items() if k in expected_keys}
            }
            log(f"年度指标 {chart_id} 更新成功：{cats[0]} ~ {cats[-1]}")
        except Exception as e:
            log(f"警告：年度指标 {chart_id} 抓取失败（不影响主要更新）：{e}")
    return results


def fetch_monthly_extras(html_164):
    """从 Cat.164/165 提取月度额外指标，返回 {key: (month_labels, series_dict)}"""
    html_165 = None
    extras = {}
    for key, cat_id, chart_id, snames in MONTHLY_EXTRA_CHARTS:
        try:
            if cat_id == 164:
                source_html = html_164
            else:
                if html_165 is None:
                    html_165 = fetch(f'https://www.pta.gov.pk/category/telecom-indicators/{cat_id}')
                source_html = html_165
            cats, series = extract_chart(source_html, chart_id)
            if cats is None:
                log(f"警告：月度额外图表 {chart_id} 未找到，跳过")
                continue
            filtered = {k: v for k, v in series.items() if k in snames}
            extras[key] = (cats, filtered)
            log(f"月度额外 {chart_id} 提取成功：{len(cats)} 个月份")
        except Exception as e:
            log(f"警告：月度额外 {chart_id} 抓取失败：{e}")
    return extras


def build_new_data_js(annual_data, history):
    """构建 AUTO-NEW-DATA 块中所有 JS 常量"""

    def jl(v):
        return json.dumps(v, ensure_ascii=False)

    def obj(d):
        return '{' + ', '.join(f'"{k}":{jl(v)}' for k, v in d.items()) + '}'

    def get(d, key, fallback=None):
        return d.get('series', {}).get(key, fallback or [])

    lines = []

    r   = annual_data.get('revenues-chart',                         {'years': [], 'series': {}})
    inv = annual_data.get('investments-chart',                       {'years': [], 'series': {}})
    fdi = annual_data.get('foreign-direct-investments-chart',        {'years': [], 'series': {}})
    mfg = annual_data.get('mobile-device-manufacturing-chart',       {'years': [], 'series': {}})
    cs  = annual_data.get('annual-cellular-mobile-cell-sites-chart', {'years': [], 'series': {}})
    arp = annual_data.get('mobile-arpu-per-month-during-year-chart', {'years': [], 'series': {}})

    lines.append(f'const annualYears = {jl(r["years"])};')
    lines.append(f'const revenues = {obj({"CMO": get(r,"CMO"), "FLL_WLL": get(r,"FLL / WLL"), "LDI": get(r,"LDI"), "TTP_TIP": get(r,"TTP/TIP"), "CVAS": get(r,"CVAS")})};')
    lines.append(f'const investments = {obj({"CMO": get(inv,"CMO"), "LDI": get(inv,"LDI"), "TTP_TIP": get(inv,"TTP/TIP"), "FLL_CVAS": get(inv,"FLL/CVAS")})};')
    lines.append(f'const fdi = {obj({"Inflow": get(fdi,"Inflow"), "Net": get(fdi,"Net FDI")})};')
    lines.append(f'const manufacturingYears = {jl(mfg["years"])};')
    lines.append(f'const manufacturing = {obj({"Smart": get(mfg,"Smart Phones"), "TwoG": get(mfg,"2G")})};')
    lines.append(f'const cellSites = {obj({"TwoG": get(cs,"2G"), "ThreeG": get(cs,"3G"), "FourG": get(cs,"4G")})};')
    lines.append(f'const arpu = {{"years":{jl(arp["years"])}, "vals":{jl(get(arp,"ARPU"))}}};')

    lines.append('const MONTHS_CN = ["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"];')

    def yoy_js(yoy_dict):
        yr_parts = []
        for yr in sorted(yoy_dict.keys()):
            inner = ', '.join(f'"{k}":{jl(v)}' for k, v in yoy_dict[yr].items())
            yr_parts.append(f'{yr}:{{{inner}}}')
        return '{' + ', '.join(yr_parts) + '}'

    ngms_yoy = build_yoy_arrays(history, 'ngmsSubs', OPERATORS + ['Total'])
    lines.append(f'const ngmsYoY = {yoy_js(ngms_yoy)};')

    raw_du = build_yoy_arrays(history, 'dataUsage', OPERATORS + ['Total'])
    du_pb = {}
    for yr, series in raw_du.items():
        du_pb[yr] = {
            k: [round(v / 1_000_000, 1) if v is not None else None for v in vals]
            for k, vals in series.items()
        }
    lines.append(f'const dataUsagePbYoY = {yoy_js(du_pb)};')

    raw_bb = build_yoy_arrays(history, 'broadband', ['Total', 'FTTH', 'Mobile BB'])
    bb_m = {}
    for yr, series in raw_bb.items():
        bb_m[yr] = {
            k: [round(v / 1_000_000, 2) if v is not None else None for v in vals]
            for k, vals in series.items()
        }
    lines.append(f'const broadbandYoY = {yoy_js(bb_m)};')

    td_yoy = build_yoy_arrays(history, 'teledensity', ['Total'])
    lines.append(f'const teledensityYoY = {yoy_js(td_yoy)};')

    return '\n'.join(lines)


def update_html(months, subs, new_data_js):
    html = HTML_FILE.read_text(encoding='utf-8')

    # ---- 1. 月度用户数（现有逻辑） ----
    months_m = re.search(r'const months = \[.*?\];', html)
    if not months_m:
        raise RuntimeError("HTML中找不到 'const months = [...]' 声明，需人工检查")
    html = html.replace(months_m.group(0), f'const months = {json.dumps(months)};', 1)

    def fmt_arr(values):
        return '[' + ','.join(str(int(v)) for v in values) + ']'

    for op in OPERATORS:
        pattern = re.compile(rf'({re.escape(op)}:\s*)\[[^\]]*\]')
        if not pattern.search(html):
            raise RuntimeError(f"HTML中找不到运营商 {op} 的数据数组，需人工检查")
        html = pattern.sub(lambda m: m.group(1) + fmt_arr(subs[op]), html, count=1)

    # ---- 2. 新数据块（sentinel 替换或首次插入） ----
    START = '// ===AUTO-NEW-DATA-START==='
    END   = '// ===AUTO-NEW-DATA-END==='
    new_block = f'{START}\n{new_data_js}\n{END}'

    existing = re.search(re.escape(START) + r'.*?' + re.escape(END), html, re.DOTALL)
    if existing:
        html = html.replace(existing.group(0), new_block)
    else:
        pos = html.find('const totals = months.map')
        if pos == -1:
            raise RuntimeError("HTML中找不到 'const totals' 插入点，需人工检查")
        insert_at = html.rfind('\n', 0, pos) + 1
        html = html[:insert_at] + new_block + '\n\n' + html[insert_at:]

    backup = None
    if not os.environ.get('CI'):
        backup = HTML_FILE.with_suffix(HTML_FILE.suffix + f".bak-{datetime.date.today().isoformat()}")
        shutil.copy2(HTML_FILE, backup)
    HTML_FILE.write_text(html, encoding='utf-8')
    return backup


def check_new_qos_reports():
    try:
        html = fetch(QOS_LIST_URL)
    except Exception as e:
        log(f"QoS报告页面抓取失败（不影响用户数据更新）：{e}")
        return

    links = sorted(set(re.findall(r'href="([^"]*(?:Quarter|qtr|Q[1-4][^"]*)[^"]*\.pdf)"', html, re.IGNORECASE)))
    known = set(json.loads(KNOWN_QOS_FILE.read_text(encoding='utf-8'))) if KNOWN_QOS_FILE.exists() else set()
    new_links = sorted(set(links) - known)

    if new_links:
        msg = (
            "检测到PTA可能发布了新的QoS季度调查报告PDF，以下链接尚未被收录进仪表盘，"
            "请人工确认是否为新一季度报告，并让Claude读取后更新HTML的'季度信号质量测试结果'部分：\n"
            + "\n".join(
                f"  - {l}" if l.startswith('http')
                else f"  - https://www.pta.gov.pk{l if l.startswith('/') else '/' + l}"
                for l in new_links
            )
        )
        QOS_ALERT_FILE.write_text(msg, encoding='utf-8')
        log("发现可能的新QoS报告，已写入 qos_update_needed.txt，请人工处理")
    else:
        if QOS_ALERT_FILE.exists():
            QOS_ALERT_FILE.unlink()

    KNOWN_QOS_FILE.write_text(json.dumps(sorted(set(links)), ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    # 1. 月度用户数（核心数据，失败即退出）
    try:
        months, subs, raw_categories, html_164 = fetch_subscriber_data()
    except Exception as e:
        log(f"更新失败（抓取/解析用户数据阶段）：{e}")
        sys.exit(1)

    # 2. 年度指标（失败不退出）
    annual_data = fetch_annual_metrics()

    # 3. 月度额外指标
    extras = fetch_monthly_extras(html_164)

    # 4. 合并到历史记录
    history = load_history()
    merge_monthly_into_history(history, 'cellularSubs', raw_categories, subs)
    for key, (month_labels, series_dict) in extras.items():
        merge_monthly_into_history(history, key, month_labels, series_dict)
    save_history(history)
    log(f"历史记录已更新，cellularSubs 共 {len(history.get('cellularSubs', {}))} 个月份")

    # 4b. 从历史记录重建顺序正确的月份数组（最近13个月）
    chart_months, chart_subs = rebuild_months_from_history(history, n_months=17)
    log(f"趋势图月份范围：{chart_months[0]} ~ {chart_months[-1]}（{len(chart_months)}个月）")

    # 5. 构建新数据 JS
    new_data_js = build_new_data_js(annual_data, history)

    # 6. 写入 HTML
    try:
        backup = update_html(chart_months, chart_subs, new_data_js)
    except Exception as e:
        log(f"更新失败（写入HTML阶段）：{e}")
        sys.exit(1)

    backup_note = f"（已备份至 {backup.name}）" if backup else "（CI环境，跳过本地备份）"
    log(f"全部数据更新成功：月度用户最新 {months[-1]}，年度指标 {len(annual_data)} 类{backup_note}")

    # 7. 检查新 QoS 报告
    check_new_qos_reports()


if __name__ == '__main__':
    main()
