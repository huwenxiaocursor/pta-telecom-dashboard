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

MONTH_MAP = {'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
             'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12}

OPERATORS = ['Jazz', 'Ufone', 'Zong', 'Telenor', 'SCO']


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


def fetch_subscriber_data():
    html = fetch(SUBSCRIBERS_URL)
    anchor = html.find('Highcharts.chart("monthly-cellular-subscribers-chart"')
    if anchor == -1:
        raise RuntimeError("找不到 monthly-cellular-subscribers-chart 锚点，PTA页面结构可能已变化，需人工检查")
    window = html[anchor:anchor + 20000]

    cat_m = re.search(r'"categories":(\[[^\]]*\])', window)
    series_m = re.search(r'series:\s*(\[\{"name":"Jazz".*?\}\])', window, re.DOTALL)
    if not cat_m or not series_m:
        raise RuntimeError("未能在锚点附近解析出 categories 或 series，需人工检查PTA页面")

    categories = json.loads(cat_m.group(1))
    series = json.loads(series_m.group(1))

    months = [to_iso_month(c) for c in categories]
    subs = {s['name']: s['data'] for s in series if s['name'] in OPERATORS}
    totals_reported = next((s['data'] for s in series if s['name'] == 'Total'), None)

    missing = [op for op in OPERATORS if op not in subs]
    if missing:
        raise RuntimeError(f"缺少运营商数据：{missing}，需人工检查")

    for i in range(len(months)):
        s = sum(subs[op][i] for op in OPERATORS)
        if totals_reported and abs(s - totals_reported[i]) > 1000:
            raise RuntimeError(
                f"{months[i]} 用户数求和({s})与PTA披露Total({totals_reported[i]})不一致，数据解析可能出错，已中止更新"
            )
    return months, subs


def update_html(months, subs):
    html = HTML_FILE.read_text(encoding='utf-8')

    months_m = re.search(r'const months = \[.*?\];', html)
    if not months_m:
        raise RuntimeError("HTML中找不到 'const months = [...]' 声明，文件结构可能被改动，需人工检查")
    html = html.replace(months_m.group(0), f'const months = {json.dumps(months)};', 1)

    def fmt_arr(values):
        return '[' + ','.join(str(int(v)) for v in values) + ']'

    for op in OPERATORS:
        pattern = re.compile(rf'({re.escape(op)}:\s*)\[[^\]]*\]')
        if not pattern.search(html):
            raise RuntimeError(f"HTML中找不到运营商 {op} 的数据数组，需人工检查")
        html = pattern.sub(lambda m: m.group(1) + fmt_arr(subs[op]), html, count=1)

    backup = None
    if not os.environ.get('CI'):
        # Local runs keep a same-day backup; in CI, git history is already the backup.
        backup = HTML_FILE.with_suffix(HTML_FILE.suffix + f".bak-{datetime.date.today().isoformat()}")
        shutil.copy2(HTML_FILE, backup)
    HTML_FILE.write_text(html, encoding='utf-8')
    return backup


def check_new_qos_reports():
    """只检测PTA是否发布了新的季度QoS城市调查报告PDF，不解析内容（图表数字需人工/AI视觉读取）。"""
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
    try:
        months, subs = fetch_subscriber_data()
    except Exception as e:
        log(f"更新失败（抓取/解析用户数据阶段）：{e}")
        sys.exit(1)

    try:
        backup = update_html(months, subs)
    except Exception as e:
        log(f"更新失败（写入HTML阶段）：{e}")
        sys.exit(1)

    backup_note = f"（已备份旧文件至 {backup.name}）" if backup else "（CI环境，跳过本地备份，git历史即备份）"
    log(f"用户/市场份额数据更新成功：最新月份 {months[-1]}，共{len(months)}个月数据{backup_note}")

    check_new_qos_reports()


if __name__ == '__main__':
    main()
