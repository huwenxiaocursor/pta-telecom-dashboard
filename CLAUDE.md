# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目简介

巴基斯坦电信与宏观经济实时信息看板，部署于 GitHub Pages：
https://huwenxiaocursor.github.io/pta-telecom-dashboard/

## 运行脚本

```bash
# PTA 电信数据更新（抓取用户数 + 年度指标）
python3 scripts/update_pta_dashboard.py

# 宏观经济数据更新（利率/储备/汇率/侨汇/CPI，需 DEEPSEEK_API_KEY，本地可从 scripts/.env.local 加载）
DEEPSEEK_API_KEY=<key> python3 scripts/update_macro_dashboard.py

# 新闻抓取与摘要生成（需设置环境变量，本地可从 scripts/.env.local 加载）
DEEPSEEK_API_KEY=<key> python3 scripts/update_news.py

# 本地日报邮件（T-1 日新闻，需 macOS + Apple Mail + Playwright）
python3 scripts/send_daily_digest.py
```

依赖安装：
```bash
pip install playwright requests pymupdf openpyxl
playwright install chromium
```

无测试框架、无 lint/build 步骤——三个页面均为纯静态 HTML，脚本靠运行后检查 `scripts/update_log.txt` / `scripts/macro_update_log.txt` / `scripts/news_update_log.txt` 验证效果。

## 三页面架构

| 文件 | 定位 | 更新脚本 |
|------|------|----------|
| `index.html` | 门户页：导航卡片 + 新闻聚合 | `update_news.py` |
| `industry_index.html` | 电信数据：用户趋势、市场份额、QoS | `update_pta_dashboard.py` |
| `macro_index.html` | 宏观经济：利率/储备/汇率/侨汇/CPI 自动更新　·　GDP/财政/产业结构/贸易人工维护 | `update_macro_dashboard.py`（部分板块，见下方"宏观年度数据维护"） |

## JS 数据注入机制

两种 sentinel 标记由脚本自动替换，手动改动这两对标记之间的内容会在下次脚本运行时被覆盖：

**电信数据**（`industry_index.html`，由 `update_pta_dashboard.py` 写入）：
```
// ===AUTO-NEW-DATA-START===
// ===AUTO-NEW-DATA-END===
```
包含：`annualYears`、`revenues`、`investments`、`fdi`、`ngmsYoY`、`dataUsagePbYoY`、`broadbandYoY`、`teledensityYoY` 等年度/月度同比常量。

月度用户数（`const months` 和运营商数组 `Jazz:`、`Ufone:` 等）在 sentinel 块之外，由 regex 直接替换。

**宏观数据**（`macro_index.html`，由 `update_macro_dashboard.py` 写入）：
```
// ===AUTO-MACRO-DATA-START===
// ===AUTO-MACRO-DATA-END===
```
包含：`const MACRO_DATA = {...}`（利率/储备/汇率/侨汇/CPI 的最新值 + 各图表滚动窗口数组）。页面内 `renderMacroData()` 函数（sentinel 块之外，脚本不会改动）负责把 `MACRO_DATA` 渲染成中文文案、涨跌箭头、动态表格和 Chart.js 图表——Python 侧只吐数字，不生成任何中文句子，与 `industry_index.html` 直接 regex 改中文文案的做法不同。
`macro_index.html` 中标注 `<!-- MANUAL -->` 注释的板块（GDP/财政/产业结构/贸易，含 `gdpChart`）不参与自动化，人工维护。

**新闻数据**（`index.html`，由 `update_news.py` 写入）：
```
// ===AUTO-NEWS-START===
// ===AUTO-NEWS-END===
```
包含：`const NEWS_DATA = [...]`。

## 数据流

```
PTA 网站 (Highcharts 内嵌数据)
    ↓ 正则提取
update_pta_dashboard.py
    ↓ merge（不覆盖已有月份）
history_monthly.json  ←── 核心数据，勿删（PTA 只保留滚动12个月）
    ↓ rebuild_months_from_history(n_months=17)
industry_index.html（sentinel 替换）

SBP war-current.asp（政策利率/外汇储备/汇率，同一页面结构化HTML）
SBP Homeremit_Arch.xlsx（侨汇，Excel，官方更新滞后）
PBS Monthly Review PDF（CPI，仅文本报告）
    ↓ 正则提取（利率/储备/汇率/侨汇）或 PyMuPDF文字提取+DeepSeek结构化抽取（CPI，附数值范围校验）
update_macro_dashboard.py
    ↓ merge_record_into_history（不覆盖已有记录）
macro_history.json  ←── 核心数据，勿删，永久保留供回溯
    ↓ rebuild_series 取各图表滚动窗口
macro_index.html（sentinel 替换 MACRO_DATA，renderMacroData() 现场渲染）

Google News RSS / WordPress REST API / PhoneWorld RSS
    ↓ is_relevant() 关键词过滤
update_news.py
    ↓ DeepSeek Chat API（200-300字中文摘要）
news_cache.json（永久缓存，含 summary_zh）
    ↓ 按日期分组，每日限5条，SOURCE_PRIORITY 排序
index.html（sentinel 替换）
```

## 自动化调度

| 任务 | 触发 | 配置文件 |
|------|------|----------|
| PTA 电信数据更新 | 每月10日、25日 10:00 PKT | GitHub Actions `.github/workflows/update.yml`（`update-industry` job） |
| 宏观经济数据更新 | 每月10日、25日 10:00 PKT | GitHub Actions `.github/workflows/update.yml`（`update-macro` job） |
| 新闻抓取 + 摘要 + commit/push | 每天 09:30 PKT | 本地 macOS launchd `scripts/com.cmpak.telecom-news-fetch.plist` → `scripts/run_news_fetch.sh` |
| 日报图片邮件（T-1 日新闻） | 每天 10:10 PKT | 本地 macOS launchd `scripts/com.cmpak.telecom-digest.plist` → `scripts/run_digest.sh` |

> `update-industry` 与 `update-macro` 是同一个 workflow 文件里的两个独立 job，共用同一个 cron，但各自独立 `git add`/`commit`/`push`/建 Issue/发邮件，互不影响、互不阻塞——一个失败不影响另一个正常更新，出问题时也能立刻定位是哪个页面的脚本挂了。两个 job 都在推送前 `git pull --rebase`，避免并发写 `main` 冲突。
>
> 新闻抓取已从 GitHub Actions 迁移到本地 launchd（`update_news.yml` 现仅保留 `workflow_dispatch` 手动触发），因为 DeepSeek Key 改为本地 `scripts/.env.local` 管理，且需要在同一次运行中 `git pull --rebase` + `commit` + `push`。`send_daily_digest.py` 默认读取昨天（T-1）的 `news_cache.json`，若当天新闻尚未抓取会自动回退到最近一次有数据的日期。摘要图片由脚本内建的 HTML 模板渲染（非 `index.html` 截图），通过 AppleScript 调用 Apple Mail 发送至 `huwenxiao@zong.com.pk`。

`update.yml` 的两个 job 在各自页面数据变更时都会自动创建 GitHub Issue 并发送邮件通知（收件人 `shawn.hwx@gmail.com`）。

CI Secrets（GitHub Actions）：`DEEPSEEK_API_KEY`、`GMAIL_USERNAME`、`GMAIL_APP_PASSWORD`（`DEEPSEEK_API_KEY` 同时被 `update-macro` job 和 `update_news.yml` 使用）。本地 launchd 任务的 `DEEPSEEK_API_KEY` 从 `scripts/.env.local`（已 gitignore）读取。

## QoS 数据维护（手动）

`update_pta_dashboard.py` 在每次运行后检查 PTA 是否发布新 QoS PDF。若有新 PDF，会写入 `scripts/qos_update_needed.txt` 并记录链接。需人工阅读 PDF，然后手动更新 `industry_index.html` 中的 `qosOverall`、`qosDownload`、`qosUpload`、`qosLatency`、`qosCCR`、`qosCSSR`、`cityWins` 等常量。

`scripts/known_qos_pdfs.json` 记录已处理的 PDF 链接列表，避免重复告警。

## 宏观年度数据维护（手动）

`macro_index.html` 中 GDP总量/人均GDP/`gdpChart`、Section③ 全部财政/产业结构/贸易板块来自《Pakistan Economic Survey》等年度或不定期报告，`update_macro_dashboard.py` **不会**自动解析这些数据（报告篇幅长、数值需要人工判断口径），只做"检测到新报告就提醒"：

`check_new_economic_survey()` 每次运行都会检查 `finance.gov.pk/survey_archieve.html` 是否出现比 `scripts/macro_known_fy.json` 记录的更新的财年。发现新一年 Economic Survey 时，会写 `scripts/macro_gdp_update_needed.txt` 提醒人工核对并更新 `macro_index.html` 中标注 `<!-- MANUAL -->` 的板块，同时把新财年记入状态文件避免重复提醒（提醒过一次后即使人工还没处理也不会再提醒，需要人工处理完后自行删除 `macro_gdp_update_needed.txt`）。

贸易数据（PBS）截至本文档更新时官方数据源URL/格式尚未确认可靠，v1 版本不做自动化，`macro_index.html` 中贸易相关卡片同样标注为人工维护，待后续确认数据源后再补充自动化。

## 宏观数据自动化的已知限制

- **CPI 抽取存在真实的 PDF 文字提取瑕疵**：PBS 月度报告 PDF 提取出的文字偶尔会把 10-19 之间的数字掉了开头的"1"（如"11.7%"被提取成"1.7%"或"1 1.7%"），`fetch_cpi()` 会把已知上月数据交给 DeepSeek 做交叉核对来修复，并做 0-50% 范围校验，但如果某月的数字恰好在合理范围内被误读（比如该改的"1"没被发现），依然可能产生小概率的错误，建议每次自动更新后抽查一次 CPI 数值。
- **侨汇（Excel归档文件）更新滞后**：`Homeremit_Arch.xlsx` 观察到有数月的滞后（不是实时反映官方新闻稿数字），`fetch_remittances()` 只会在归档文件真正更新到新月份时才产生新记录，中间可能连续多次运行都"无新增"，属正常现象。
- **CPI 的 NFNE 核心通胀字段**仅在 PBS 报告"Inflation in Brief"摘要段落包含时才会被抽取，若某月报告未在该段落提及，页面会保留上次已知值而非清空。

## 注意事项

- `history_monthly.json` 中 2025-01 至 2025-04 数据为人工补录，PTA 已无法再提供这些月份数据，禁止覆盖。
- `macro_history.json` 是宏观数据的永久历史，只增不覆盖，禁止删除或覆盖已有记录——`macro_index.html` 里的图表只展示滚动窗口，完整历史全部在这个文件里，供以后回溯。
- PTA 页面结构变化时正则提取会失败，运行后检查 `scripts/update_log.txt`；SBP `war-current.asp` 页面结构变化时检查 `scripts/macro_update_log.txt`。
- 本地推送前先 `git pull --rebase`，避免与 GitHub Actions 自动提交冲突。
- 新闻源优先级（高→低）：PTA > ProPakistani > SBP > PhoneWorld > TechJuice，同日相似标题会去重（保留高优先级来源）。
