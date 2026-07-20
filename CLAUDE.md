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

# Zong 套餐清单更新（全量抓取 zong.com.pk 预付费+后付费，无需 Key，纯标准库）
python3 scripts/update_zong_packages.py

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

## 五页面架构

| 文件 | 定位 | 更新脚本 |
|------|------|----------|
| `index.html` | 门户页：顶部 hero（第一行内嵌「中方员工生活用品需求」申请表单，字段横排；第二行 4 个数据看板跳转卡片横排）+ 新闻聚合。**表单为纯前端**，`fetch()` POST 到 Google Apps Script（`APPS_SCRIPT_URL` 常量），后端在 Apps Script 侧、不在本仓库；原独立页 `supplies_form.html` 已删除，此处为唯一版本 | `update_news.py`（仅新闻区，表单无脚本） |
| `industry_index.html` | 电信数据：用户趋势、市场份额、QoS | `update_pta_dashboard.py` |
| `macro_index.html` | 宏观经济：利率/储备/汇率/侨汇/CPI 自动更新　·　GDP/财政/产业结构/贸易人工维护 | `update_macro_dashboard.py`（部分板块，见下方"宏观年度数据维护"） |
| `zong_packages_index.html` | Zong 预付费/后付费套餐清单（含国际漫游/IDD、Apna Shehr/Area Play 地区套餐），支持搜索与分类筛选 | `update_zong_packages.py`，每两个月全量抓取 zong.com.pk（见下方"Zong 套餐清单自动化"） |
| `government_statement.html` | 中巴友谊政府通告声明：时间轴形式收录 1956–2026 年中巴官方声明的首提概念/经典描述/领导人发言要点，支持搜索、年份筛选、只看首提概念，从 `index.html` 导航卡片进入 | 无脚本；数据内嵌于页面 `<script id="data">` 的 JSON，人工维护（新增记录直接改该 JSON 数组；`/` 为无内容占位符，前端加载时清洗成空） |

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

**Zong 套餐数据**（`zong_packages_index.html`，由 `update_zong_packages.py` 写入）：
```
// ===AUTO-ZONG-START===
// ===AUTO-ZONG-END===
```
包含整个 `const PLANS = [...]` 数组。另有一处 `<!--ZONG-DATE-START-->…<!--ZONG-DATE-END-->` 标注采集年月，脚本同时替换。sentinel 之外的 `SEC`（分类定义）、`ORDER`、筛选 chip、`render()` 逻辑均为人工维护，脚本不动。

## Zong 套餐清单自动化

`update_zong_packages.py` 每两个月**全量**抓取 `zong.com.pk/prepaid` 和 `/postpaid`，覆盖预付费/后付费主套餐、国际漫游/IDD、Apna Shehr/Area Play 地区套餐（约 500 个/次），按 slug 去重后重建 `PLANS`。设计要点：

- **服务端渲染，纯正则解析**：每张卡是 `<article class="card single_bundle …">`，名称在 `<a href=".../prepaid|postpaid/{slug}">`、有效期在 `<small>`、价格在 `PKR. xxx`、套餐内容在 `<div class="specs_col">数字单位 <span>标签</span></div>`。同一 slug 常在"热门"和分栏里重复，按 slug 去重保留首现。
- **确定性规则翻译，不用 LLM**：套餐内容英文词汇表很小且固定（`GB`/`Zong Mins`/`Off-net Mins`/`All Net Mins`/`Int Mins`/`SMS`/`Total Data`/`Internet`），`tr_feat()` 逐条映射成中文（流量/Zong分钟/跨网分钟/全网分钟/国际分钟/条短信），无法识别的原样保留、绝不编造。刻意不引入 DeepSeek——避免 LLM 脑补价格或套餐内容（与新闻/CPI 脚本的教训一致）。
- **规则分类**：`category()` 顺序敏感——先按名称/国家关键词判 `roaming`，再判 `area`（Apna Shehr/Area/克什米尔），再按 app 关键词判 `app`/`vas`，最后按"有无流量/有无语音"落到 `data`/`voice`/`hybrid`。
- **安全阀**：抓取异常或去重后套餐数 `< MIN_EXPECTED(200)` 时 `sys.exit(1)` 中止并**保留原页面**，不写半截数据。页面结构变化时会因此报错，需人工检查官网 HTML。
- **不留历史**：页面是当前快照，每次全量覆盖，靠 git diff 判断是否有变化（无 `*_history.json`）。运行后检查 `scripts/zong_update_log.txt`。

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

Google News RSS / WordPress REST API / Dawn + Business Recorder RSS
    ↓ is_relevant() 关键词过滤
    ↓ fetch_article_text()：抓取文章正文（best-effort，失败则空字符串）
update_news.py
    ↓ DeepSeek Chat API（200-300字中文摘要 + 重要性分级，同一次调用完成）
news_cache.json（永久缓存，含 summary_zh、importance、dup_of）
    ↓ mark_duplicates()：确定性实体重叠去重（跨天窗口，见下），命中即写 dup_of 持久化
    ↓ 按日期分组（跳过 dup_of 条目）；字符串近似去重(逐天) + LLM当次语义去重(对最近
    ↓ DEDUP_LOOKBACK_DAYS天窗口整体跑一次、跨天，不持久化)；去重后当天候选覆盖的distinct来源数 ≥
    ↓ MIN_SOURCES_PER_DAY(3) 才用 MAX_PER_DAY(8) 上限，否则降级为
    ↓ LOW_DIVERSITY_CAP(5)——避免一两家媒体的产出把当日新闻栏"撑满"；
    ↓ PTA标题前置(封顶MAX_PTA_PER_DAY)优先，同级再按 IMPORTANCE_PRIORITY、
    ↓ SOURCE_PRIORITY 排序；ensure_source_diversity()尽力换入不同来源但不
    ↓ 强凑（候选本身来源不够时如实展示，不会为了凑数/凑渠道编造数据）
index.html（sentinel 替换）
```

**重要**：`summarize()` 必须传入 `fetch_article_text()` 抓到的正文（`article_text` 参数）。
DeepSeek 的 Chat API 本身无法访问URL，如果只传标题，它会"脑补"出一篇像模像样但数字/日期
全是虚构的摘要（2026-07-02 发现的真实事故：一条PhoneWorld新闻被脑补出"2023-24财年降12%"，
实际原文是"FY22-23至FY24-25降至353亿卢比"，财年区间和数字全部对不上）。`fetch_article_text()`
抓取失败时会返回空字符串，此时 `summarize()` 的prompt会切换到"只看标题"模式，并明确禁止
编造标题之外的具体数字/日期——但即便如此也应优先保证正文抓取成功率，别指望这层兜底当常态。

**正文抓取分三路**（2026-07-19 定）：

1. **RSS 自带全文**——Dawn 和 Business Recorder 的 feed 在 `<content:encoded>`/`<description>`
   里就带整篇正文，`rss_body()` 取出后塞进 item 的临时键 `article_text`，`main()` 用
   `item.pop("article_text", "") or fetch_article_text(url)` 消费。**`pop` 是刻意的**，这个键
   绝不能落进 `news_cache.json`。
2. **纯 HTTP 抓页面**——`fetch_article_text()` 的快路径，覆盖 ProPakistani / TechJuice。
3. **真浏览器兜底**——`fetch_article_text_browser()`，前两路都空时启用 Playwright
   （已是本项目依赖，日报截图在用）。`_BROWSER` 模块级复用，`main()` 结尾 `close_browser()`。

> 血的教训（2026-07-19）：**brecorder.com 的文章页对脚本请求一律 403**（反爬按 TLS 指纹/JS
> 挑战判定，不是 User-Agent——换完整浏览器请求头、AMP 域名、第三方代理全都无效；但 RSS
> feed 不设防，**真浏览器也完全打得开**）。结果是 2026-07-02 引入 BR 后它的**每一条**新闻都
> 静默走了 title-only 模式，18 条摘要全是 DeepSeek 脑补——最典型的 "June mobile phone
> manufacturing falls 12pc YoY" 被写成"2023年6月"，原文是 2026 年 6 月（本地组装 193 万台
> vs 去年同期 219 万台）。这 18 条已用 Playwright 抓到真正文后**全部重新生成**，未丢数据。
>
> 教训三条：
> (1) **新增新闻源必须单独验证 `fetch_article_text()` 对该站真拿得到正文**，别假设 RSS 抓得到
> 就等于文章页抓得到；
> (2) 403/抓不到时**先试真浏览器再下结论**——"用 curl 打不开"不等于"抓不到"，本项目一开始就
> 有 Playwright；
> (3) 降级到 title-only 以前完全无声，现在 `main()` 会打
> `! no article text — title-only summary (may be unreliable)`，上新源后和日常巡检都该在
> `scripts/news_update_log.txt` 里 grep 这行。

`fetch_article_text_browser()` 里那次"读到的正文 < 200 字就等 6 秒重读一遍"不是保险起见：
Google News RSS 的链接是 **JS 跳转中转页**，`domcontentloaded` 时 body 还是那张近乎空白的
弹跳页，直接读会得到空字符串并误判成"没正文"。等一次再读才会落到发布方的真实文章页
（实测 `news.google.com/rss/articles/...` → `thenews.pk/print/...`，6366 字）。

## 自动化调度

| 任务 | 触发 | 配置文件 |
|------|------|----------|
| PTA 电信数据更新 | 每月10日、25日 10:00 PKT | GitHub Actions `.github/workflows/update.yml`（`update-industry` job） |
| 宏观经济数据更新 | 每月10日、25日 10:00 PKT | GitHub Actions `.github/workflows/update.yml`（`update-macro` job） |
| Zong 套餐清单全量刷新 | 每两个月（1/3/5/7/9/11月）10日 10:00 PKT | GitHub Actions `.github/workflows/update_zong.yml`（`update-zong` job，独立 workflow 因 cron 不同） |
| 新闻抓取 + 摘要 + commit/push | 每天 09:30 PKT | 本地 macOS launchd `scripts/com.cmpak.telecom-news-fetch.plist` → `scripts/run_news_fetch.sh` |
| 日报图片邮件草稿（T-1 日新闻，密送多人，人工确认后手动发送） | 每天 10:10 PKT | 本地 macOS launchd `scripts/com.cmpak.telecom-digest.plist` → `scripts/run_digest.sh` |

> `update-industry` 与 `update-macro` 是同一个 workflow 文件里的两个独立 job，共用同一个 cron，但各自独立 `git add`/`commit`/`push`/建 Issue/发邮件，互不影响、互不阻塞——一个失败不影响另一个正常更新，出问题时也能立刻定位是哪个页面的脚本挂了。两个 job 都在推送前 `git pull --rebase`，避免并发写 `main` 冲突。
>
> 新闻抓取已从 GitHub Actions 迁移到本地 launchd（`update_news.yml` 现仅保留 `workflow_dispatch` 手动触发），因为 DeepSeek Key 改为本地 `scripts/.env.local` 管理，且需要在同一次运行中 `git pull --rebase` + `commit` + `push`。`send_daily_digest.py` 默认读取昨天（T-1）的 `news_cache.json`（实际读取的是 `index.html` 里已经排好序/去重/过滤空摘要的 `NEWS_DATA`，不是直接读 `news_cache.json` 重新计算，见脚本 `load_today_news()` 注释）。**2026-07-13起改为：若 T-1 当天无新增新闻，不再回退到旧日期把旧新闻当日报再发一遍**——此时跳过日报草稿，改为只给本人（`NOTIFY_EMAIL`，收件人栏，不密送 18 人、不带附图）在草稿箱生成一封纯文字提醒邮件（说明当天无新增、最近有数据的日期），同样只 `save` 不 `send`。摘要图片由脚本内建的 HTML 模板渲染（非 `index.html` 截图）。**2026-07-04起改为生成邮件草稿而非自动发送**：通过 AppleScript 把 `scripts/send_daily_digest.py` 里 `BCC_EMAILS` 列表（18人）全部放进密送栏，只 `save` 到 Apple Mail 的草稿箱，不调用 `send`——由用户在草稿箱人工确认后手动发送。

`update.yml` 的两个 job 在各自页面数据变更时都会自动创建 GitHub Issue 并发送邮件通知（收件人 `shawn.hwx@gmail.com`）。

CI Secrets（GitHub Actions）：`DEEPSEEK_API_KEY`、`GMAIL_USERNAME`、`GMAIL_APP_PASSWORD`（`DEEPSEEK_API_KEY` 同时被 `update-macro` job 和 `update_news.yml` 使用）。本地 launchd 任务的 `DEEPSEEK_API_KEY` 从 `scripts/.env.local`（已 gitignore）读取。

## QoS 数据维护（手动）

`update_pta_dashboard.py` 在每次运行后检查 PTA 是否发布新 QoS PDF。若有新 PDF，会写入 `scripts/qos_update_needed.txt` 并记录链接。需人工阅读 PDF，然后手动更新 `industry_index.html` 中的 `qosOverall`、`qosDownload`、`qosUpload`、`qosLatency`、`qosCCR`、`qosCSSR`、`cityWins` 等常量。

`scripts/known_qos_pdfs.json` 记录已处理的 PDF 链接列表，避免重复告警。

## 年度指标人工覆盖（`scripts/annual_overrides.json`）

PTA 官网部分年度指标图表（`ANNUAL_SOURCES` 里的6类：营收、投资、FDI、设备制造、基站、ARPU）会出现长期不更新的情况——比如 `mobile-arpu-per-month-during-year-chart` 截至2026-07仍停留在2022-23，但同期的 *PTA Annual Report* PDF 里已经有更新数值。遇到这种情况，人工从年报PDF提取数据后写入 `scripts/annual_overrides.json`，`fetch_annual_metrics()` 会在每次运行时通过 `apply_annual_override()` 合并：**覆盖文件里有的年份一律用覆盖值**（即使官网当时也有该年份但数值不同，如ARPU的FY21-22/FY22-23官网237/242 vs 年报212/229，以年报为准），**覆盖文件里没有的年份继续沿用官网抓取值**。这样人工修正不会被下次自动抓取悄悄覆盖回去。

给年报PDF提取数字配对年份时要注意：PTA年报的单年份图表标签（如"2025"）通常代表**财年结束年**（对照报告里同一文档"—FY"或"as of June"标注的图表来确认惯例），不是自然日历年；提取时最好用 `page.get_text('words')` 拿到每个数字和年份标签的坐标，按x轴位置对齐，不要只看文字顺序（同一图表里多个数值可能因为高度接近被合并进同一个文本块，导致读取顺序和视觉顺序不一致）。

## 宏观年度数据维护（手动）

`macro_index.html` 中 GDP总量/人均GDP/`gdpChart`、Section③ 全部财政/产业结构/贸易板块来自《Pakistan Economic Survey》等年度或不定期报告，`update_macro_dashboard.py` **不会**自动解析这些数据（报告篇幅长、数值需要人工判断口径），只做"检测到新报告就提醒"：

`check_new_economic_survey()` 每次运行都会检查 `finance.gov.pk/survey_archieve.html` 是否出现比 `scripts/macro_known_fy.json` 记录的更新的财年。发现新一年 Economic Survey 时，会写 `scripts/macro_gdp_update_needed.txt` 提醒人工核对并更新 `macro_index.html` 中标注 `<!-- MANUAL -->` 的板块，同时把新财年记入状态文件避免重复提醒（提醒过一次后即使人工还没处理也不会再提醒，需要人工处理完后自行删除 `macro_gdp_update_needed.txt`）。

贸易数据（PBS）截至本文档更新时官方数据源URL/格式尚未确认可靠，v1 版本不做自动化，`macro_index.html` 中贸易相关卡片同样标注为人工维护，待后续确认数据源后再补充自动化。

## 宏观数据自动化的已知限制

- **CPI 抽取存在真实的 PDF 文字提取瑕疵**：PBS 月度报告 PDF 提取出的文字偶尔会把 10-19 之间的数字掉了开头的"1"（如"11.7%"被提取成"1.7%"或"1 1.7%"），`fetch_cpi()` 会把已知上月数据交给 DeepSeek 做交叉核对来修复，并做 0-50% 范围校验，但如果某月的数字恰好在合理范围内被误读（比如该改的"1"没被发现），依然可能产生小概率的错误，建议每次自动更新后抽查一次 CPI 数值。
- **侨汇（Excel归档文件）更新滞后**：`Homeremit_Arch.xlsx` 观察到有数月的滞后（不是实时反映官方新闻稿数字），`fetch_remittances()` 只会在归档文件真正更新到新月份时才产生新记录，中间可能连续多次运行都"无新增"，属正常现象。
- **CPI 的 NFNE 核心通胀字段已不再自动抓取**（覆盖不稳定，价值有限），`macro_index.html` 中已移除对应展示卡片；`macro_history.json` 里此前已存的 `nfneUrbanYoy`/`nfneRuralYoy` 历史值保留不删，仅不再新增。

## 运营商名单变化检测（Telenor × Ufone 合并预案）

巴基斯坦运营商合并（PTCL/e& 收购 Telenor Pakistan，预计整合进 Ufone）后，PTA 月度用户数图表迟早会不再单列 Telenor，或改出一个新公司名。`update_pta_dashboard.py` 通过 `check_operator_roster()` 在每次抓完用户数图后自动检测这类口径变化，**目的是给人工一个明确反馈、由人确认后再重建页面，而不是让脚本自己崩或自己猜**：

- 把 PTA 当前实际提供的运营商 series（排除 `Total`）与基线 `scripts/known_operators.json` 对比。
- 名单不变 → 静默继续，并清除可能残留的 `operators_changed_needed.txt`。
- 出现新增/消失 → 写 `scripts/operators_changed_needed.txt`（列出：新增/消失了哪些运营商、PTA 当前的完整运营商维度、本看板追踪的全部数据维度、处理提示），并**抛错中止本次更新**（不写历史，避免混入不同口径数据）。
- 该检测**刻意排在旧的「缺少运营商数据」missing 校验之前**——否则 Telenor 一消失会先被那个含糊错误拦下，给不出有用反馈。

发现变化后的人工闭环：
1. 读 `operators_changed_needed.txt`，确认是否为合并/改名。
2. 决定新公司的呈现方式（延续 `Ufone` 使份额曲线连续，还是新命名）、配色，以及 **YoY 口径**——合并后新公司必须与「去年被并各方之和」对比，否则会显示虚假暴涨。
3. 让 Claude 重新生成 `industry_index.html`：同步更新 `OPERATORS` 常量与页面里的 `COLORS`、月度用户数数组、`qosOverall/qosRank/qosDownload/...`、`cityWins`、排名趋势表。
4. 合并前各运营商的历史数据保留原口径，勿覆盖（沿用本仓库只增不覆盖惯例）。
5. 把 `scripts/known_operators.json` 改成新名单以解除提醒——否则每次运行都会继续中止（与 `macro_gdp_update_needed.txt` 需人工处理后清除同理）。

## 注意事项

- `history_monthly.json` 中 2025-01 至 2025-04 数据为人工补录，PTA 已无法再提供这些月份数据，禁止覆盖。
- `macro_history.json` 是宏观数据的永久历史，只增不覆盖，禁止删除或覆盖已有记录——`macro_index.html` 里的图表只展示滚动窗口，完整历史全部在这个文件里，供以后回溯。
- PTA 页面结构变化时正则提取会失败，运行后检查 `scripts/update_log.txt`；SBP `war-current.asp` 页面结构变化时检查 `scripts/macro_update_log.txt`。
- 本地推送前先 `git pull --rebase`，避免与 GitHub Actions 自动提交冲突。
- `is_relevant()` 关键词过滤带**地域校验**（2026-07-12 加）：命中电信/宏观关键词后，若标题明显在讲外国（`_FOREIGN`：Thai/India/China 等国家词，子串匹配；外加 `_FOREIGN_WB`：`us`/`uk`/`eu`/`opec` 等**缩写按整词匹配**——2026-07-16 补，否则 `us` 会误伤 `business`/`focus`）且完全不含巴基斯坦标识（`_PK_MARKERS`：Pakistan/SBP/PTA/Karachi 及四大运营商等）则否掉。因为 `_TELECOM_SUB` 里的宏观词（`central bank`/`inflation rate`/`interest rate`/`monetary policy`…）是全球通用的，而 BusinessRecorder 会转发 Reuters/AFP 的外国新闻（真实事故：泰国"central bank chief"通胀新闻因命中 `central bank` 混进看板；2026-07-16 又发现"Asian stocks gain on drop in US inflation rate"因 `_FOREIGN` 当时不含美式缩写 `US`/`asian stock` 而漏拦——已补 `_FOREIGN_WB` + `asian stock/market`、`wall street`、`us inflation/fed/treasury` 等短语）。这类被 `is_relevant()` 否掉的条目：抓取入口拒收，且每次运行都会对整份 `news_cache.json` 全量回扫剔除（`main()` 里 `cache = [i for i in cache if is_relevant(...)]`），历史残留会自愈清除。反过来，宏观词覆盖也要留意漏收：IMF 相关只列了 `imf program/review/tranche/loan/talks/funding/disbursement/bailout` 这些**相邻短语**，`IMF approves…disbursement` 这种词被隔开的仍匹配不上——发现漏收的正当新闻时优先补 `_TELECOM_SUB` 关键词，别去松动地域校验。
- 新闻源优先级（高→低）：PTA > ProPakistani > SBP > Dawn > BusinessRecorder > TechJuice，同日相似标题会去重（保留排序更靠前的一条，即重要性更高、来源优先级更高的）。Dawn 于2026-07-19加入（`fetch_dawn()`，Business RSS），排在 BusinessRecorder 之前——巴基斯坦英文报纸中的权威大报，但电信稿量小，`is_relevant()` 过滤后每次通常只有个位数条目。PhoneWorld 已于2026-07-02因质量问题（会把过时新闻当新内容重新发布）被 Business Recorder 替换，**2026-07-19 起彻底移除**：配色常量、`news_cache.json` 与 `index.html` 里残留的2条历史条目一并删除（`industry_index.html` 的 QoS 历史排名出处引用保留，那是对既有报道的事实标注，不是新闻源配置）。
- `fetch_google_news()` 过去**不做 `is_relevant()` 过滤**（其他所有 fetcher 都做），不相关标题会一路走到 `summarize()`，白烧一次 DeepSeek 调用，最后才被入库前的全量回扫剔掉——2026-07-19 的一次运行里 10 条新条目有 6 条如此。已在该函数内补上过滤，最终缓存内容不变，只是不再浪费调用。
- Dawn 和 Business Recorder 都是**综合财经 RSS**（`fetch_rss_feed()` 共用解析），不是电信垂直源，大部分条目与看板无关且都会转发 Reuters/AFP 的外国新闻，因此 `is_relevant()` 的地域校验对这两家尤其关键（见上一条）。新增同类 RSS 源时直接复用 `fetch_rss_feed(feed_url, source_label, display_name)`，不要再复制一份解析逻辑。
- 新闻重要性分级：`summarize()` 让 DeepSeek 在生成摘要的同时判定"高/中/低"，标准是 (1) 是否涉及四大主流运营商（Jazz/Zong/Telenor/Ufone）或SBP/PTA监管动作，完全不涉及（如中小ISP、SCO等边缘运营商）判"低"；(2) 即使涉及主流运营商/监管机构，若只是常规新闻（非监管处罚/并购/财报/重大政策）也判"中"而非"高"。每日展示时PTA标题新闻优先前置（封顶`MAX_PTA_PER_DAY`3条），同级再按重要性、来源排序，"低"重要性新闻常因当天候选超过展示上限（`MAX_PER_DAY`8条，或来源不够3个时降级为`LOW_DIVERSITY_CAP`5条）被挤出展示，但仍完整保留在 `news_cache.json` 里。旧缓存中没有 `importance` 字段的条目不会被批量回填，排序时按"中"处理。
- 标题含"PTA"的新闻在每日展示中优先前置，但封顶 `MAX_PTA_PER_DAY`（3条/5条），避免PTA新闻多的时候把其他来源全部挤掉；超出封顶的PTA新闻会和非PTA新闻放在一起按重要性/来源优先级重新竞争剩余名额。
- 跨源同事件去重是**三层**（都只处理最近 `DEDUP_LOOKBACK_DAYS`(3天)内的新闻；第1、2层作用于整个窗口即**跨天**，第3层仍逐天；同一事件保留**日期更早**的一条——即昨天已展示过的那条，今天重复的那条被标记去掉，符合"当天和前一天比对去重"）：
  1. **`mark_duplicates()` 确定性实体重叠去重（唯一持久化的一层，跨天）**：把最近 `DEDUP_LOOKBACK_DAYS` 天的候选**汇成一个池**（而非逐天），提取标题里窗口内低频的显著词（人名/机构缩写等，出现文档数 ≤ `ENTITY_RARE_DF_MAX`，排除 Ufone/Telenor/merger 这类高频话题词），两条共享的稀有词 ≥ `ENTITY_OVERLAP_MIN_RARE`(3) 即判为同一事件，给日期更晚的一条写 `dup_of`（保留条即较早那条的url）存进 `news_cache.json`。df 按整窗口算，所以跨多天共现的话题词自然变高频被排除，跨天阈值和原来逐天一样保守，绝不会把滚动事件的不同进展误合并。**决策一旦落盘就固定**，展示时直接跳过 `dup_of` 条目——防止"已去重的新闻下次又冒出来"。幂等：重复运行结果一致，已标记的不复算。
  2. **`llm_dedup_groups()` LLM语义去重（当次展示用，不持久化，跨天）**：对最近 `DEDUP_LOOKBACK_DAYS` 天窗口**整体跑一次**（非逐天），用DeepSeek识别措辞差异大、实体兜底抓不到的**跨天同事件重复**——这正是常见的跨天重复形态（不同媒体隔天用不同措辞报同一事件，共享稀有词 < 3，确定性层抓不到，只有LLM能识别；例如 TechJuice "PTA Fines Jazz, Zong, Ufone and Telenor Rs740 Million" 与次日 BusinessRecorder "PTA imposes Rs740m penalties on four cellular mobile operators"）。保留较早一天、去掉较晚一天，只过滤当次展示。**刻意不持久化**：DeepSeek 即使 `temperature=0` 也非确定性，且偶尔会把同话题不同角度的新闻（如合并后的"资费上涨"vs"员工裁员"vs"暂停改名"）**过度合并**成一条——跨天窗口更容易踩到这种误判，若落盘会永久误删不同新闻，所以只让它影响单次展示、下次自我纠正。
  3. **字符串近似去重（逐天）**：兜底同一天标题字面几乎相同的残留。
  > 背景（2026-07-07）：曾出现 ProPakistani"PTCL's Chief People Officer Umer Farid Joins PSTD Board of Governors"与 TechJuice"PTCL CPO Umer Farid Appointed to PSTD Board of Governors"同日重复展示——两条明明同事件，但那次运行 DeepSeek 漏判了（temp=0 也不保证跨调用一致）。加确定性实体兜底(层1)+持久化正是为根治这类"LLM间歇性漏判导致重复反复出现"。
