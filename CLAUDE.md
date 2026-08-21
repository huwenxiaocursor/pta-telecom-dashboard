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

无测试框架、无 lint/build 步骤——五个页面均为纯静态 HTML（GitHub Pages 直接托管仓库根目录），脚本靠运行后检查 `scripts/update_log.txt` / `scripts/macro_update_log.txt` / `scripts/news_update_log.txt` 验证效果。

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

pta.gov.pk 官网三个栏目（Playwright 渲染）/ Google News RSS / WordPress REST API
  / Dawn + Business Recorder RSS
    ↓ is_relevant() 关键词过滤 + CUTOFF_DATE(2026-08-01) 日期下限
    ↓ fetch_article_text()：抓取文章正文（best-effort，失败则空字符串）
    ↓ 顺带解析文章自带发布时间（_LAST_PUB_DATE），与 RSS 日期差 >
    ↓ STALE_DATE_TOLERANCE_DAYS(2) 天时以文章为准，早于 CUTOFF_DATE 直接丢弃
update_news.py
    ↓ DeepSeek Chat API（中文摘要 + 重要性分级，同一次调用完成）
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

## 新闻源构成（2026-08-13 大改，勿退回旧模型）

- **PTA 官方原文由 `fetch_pta_official()` 直抓 `pta.gov.pk`**（press-releases / news-updates / public-notices 三个栏目，`PTA_SECTIONS`）。此前"PTA"这个来源标签挂的是 Google News 搜出来的**媒体报道**，点开落到 ProPakistani/TechJuice，名不副实。该站是 SPA，**必须用真浏览器**：纯 HTTP 只拿到页面外壳，条目全由 JS 渲染，栏目页之外的路径对 curl 直接 302；且文章 URL 也长在 `/category/` 下（与栏目页同前缀），**按路径前缀过滤会把文章一起滤掉**（探查时栽过一次）。招标栏目（`/category/tenders`）是采购信息，刻意不抓。
- **Google News 只是打开既定目标媒体的通道，不是引进新媒体的入口**（用户明确）。`fetch_google_news(query, source_label)` 的 `source_label` 只是这一路查询的名字，**不作为条目来源**——`_gn_publisher()` 从 RSS 的 `<source>` 取真实发布方，经 `_GN_PUBLISHER_MAP` 归一化后，不在 `_GN_ALLOWED_PUBLISHERS`（即 `SOURCE_PRIORITY` 的键）里的一律丢弃。Mettis Global、ARYnews、Bloom Pakistan 等未经评估的媒体不收，这也顺带挡住了已被移出信源的 PhoneWorld。
- **`CUTOFF_DATE`（当前 `2026-08-01`）是抓取日期下限**，早于该日的新条目一律不收。2026-08-13 从 `2026-01-01` 上调：修好 Google News 的排序/时间窗问题后，PTA、SBP 两源积压的历史条目会一次性涌进来。已入库的历史条目不受影响（过滤只作用于新抓取，同 `--reclean` 那条约定）。
- **RSS 日期不可尽信，用文章自带发布时间校正**：`fetch_article_text()` 抓正文时顺手用 `_extract_pub_date()` 解析 JSON-LD `datePublished` / OpenGraph `article:published_time` / `<time datetime>`（按可信度排序），存进模块级 `_LAST_PUB_DATE`（刻意不改函数签名——该函数有多个调用点和一条浏览器兜底路径；抓取严格单线程顺序执行，紧跟调用之后读取）。与 RSS 日期相差超过 `STALE_DATE_TOLERANCE_DAYS`(2) 天就以文章为准，校正后早于 `CUTOFF_DATE` 的直接丢弃——拦的是媒体把旧文重新推送当新闻。校正逻辑收在 `_apply_real_pub_date(item) -> bool`（返回 `False` 即该条应丢弃），**`main()` 的 new_items 和 retry_items 两条路径都必须调用它**，且必须紧跟在 `fetch_article_text()` 之后（它读的 `_LAST_PUB_DATE` 就是那次抓取的副产物）。
  > **2026-08-15 补的洞**：`retry_items` 分支此前不做日期校正，而它处理的恰恰是"上次没抓到正文"的条目——上次拿不到正文就等于上次的日期从未被校正过，正是最可能混着旧文的一批。当天 Playwright 浏览器二进制被清掉（见下条），13 条走了 title-only 入库，补跑重摘要时这条路径一开就暴露：**其中 9 条根本是 2～7 月的旧文**被 TechJuice/Google News 重新推送，标题极具迷惑性（《PTA approves Ufone-Telenor Merger》标成 08-11，原文 03-19；《PTA Proposes Lifetime Validity for Prepaid Mobile Balance》标成 08-09，原文 02-27）。补上校正后这 9 条全部被丢弃。
- **不要删 `~/Library/Caches/ms-playwright/`——它不是缓存垃圾，是本项目的运行依赖**。2026-08-14 晚它被人工当作缓存清掉（用户排查别的问题时手动删除；playwright 包本身没动，仍是 6-24 装的 1.60.0），次日两个定时任务全线受影响。这个目录名字长在 `Caches` 下、体积约 200MB、不属于任何已安装 App，看起来极像垃圾，但 `fetch_pta_official()`、正文抓取的浏览器兜底、日报出图全靠它。误删后重装：`python3 -m playwright install chromium`。
- **浏览器一没，故障是静默的——排查任何"新闻不对劲"先查这个**。后果分两半，**只有一半会报错**：
  - 10:10 的日报任务直接崩在 `html_to_png()` 的 `p.chromium.launch()`，`/tmp/telecom_digest.log` 里有完整 traceback，草稿根本没生成——这半容易发现。
  - 09:30 的抓新闻任务**照常跑完、照常 commit/push、退出码 0**：PTA 官网整源被 `fetch_pta_official()` 的 try/except 吞掉（只留一行"浏览器不可用，跳过"），Google News 的 JS 中转页拿不到正文全部降级 title-only，**日期校正也随之失效**（`_LAST_PUB_DATE` 是抓正文的副产物），于是旧文当新闻一路混进库。
  - 排查入口：`launchctl list | grep cmpak` 看退出码只能发现前一半；真正该 grep 的是 `scripts/news_update_log.txt` 里的 `浏览器不可用` 和 `no article text`。修复：`python3 -m playwright install chromium`（约 92MB）。
- **Cloudflare 挑战有浏览器兜底**：`fetch_with_browser_fallback()` 先 curl，`_is_cloudflare()`（响应 < 8KB 且含 `challenges.cloudflare.com`）判定为挑战页时改用 Playwright 重取。`_fetch_page_source_browser()` 对 JSON 端点取 `innerText`（Chrome 会把 `application/json` 包进 `<pre>`），HTML/XML 取 `page.content()`。

## 抓取失败诊断（`scripts/fetch_status.json`）

**"今天 0 条"有四种完全不同的成因，页面上长得一模一样**——任务照常跑完、退出码照样是 0、`index.html` 照常重写，只是内容是空的。`_diagnose_fetch_health()` 每轮判定一次，结论写进 `scripts/fetch_status.json`，`send_daily_digest.py` 的 `fetch_health_note()` 读出来写进那封"今天无新增"的提醒邮件——**用户看邮件，不看日志**，报警不进邮件等于没报。

| status | 含义 | 处理 |
|--------|------|------|
| `ok` | 抓取和摘要都正常，确系当天无符合条件的新稿 | 不用管 |
| `network` | 出现"连不上"级错误（curl 退出码 6/7/28/35/56），且无任何源拿到内容 | 联网后补跑，新闻会一并找回 |
| `summary` | **新闻抓到并已入库，但摘要调用全部失败** | 解决后重跑即可自动补齐，无需重抓 |
| `sources` | 网络正常但所有源都返回 0 条 | 可能真无新稿，也可能某站改版打挂了解析，人工核对 |

两次真实事故（都发生在 2026-08-17～18，同一天内被连着撞上）：

- **断网空转**：8-17、8-18 两天 09:30 的任务准时触发，但全部源 `Could not resolve host`、Playwright 报 `ERR_INTERNET_DISCONNECTED`——Mac 刚唤醒、Wi-Fi 还没连上。当天页面显示"无新闻"，实际补跑后抓回 24 条，其中包括 PTA 罚运营商 34.1 亿卢比、5G 频谱拍卖 5.07 亿美元这类重头新闻。
- **DeepSeek 余额耗尽**：补跑把新闻抓回来了，但摘要一条都没生成。**DeepSeek 出错时照样返回 HTTP 200，错误在 body 里**（`{"error":{"message":"Insufficient Balance"}}`），`summarize()` 原先直接取 `result["choices"]`，上层只看到 `KeyError: 'choices'`，完全看不出是没钱了。现在 `summarize()` 显式检查 `error` 字段并把原文存进 `_LLM_STAT["last_error"]`，诊断层再据此给出"余额不足/Key 无效/触发限流"的具体指引。**空摘要条目不展示但已入库**，`retry_items` 分支下次运行会自动补摘要，不必重抓。

> **`_diagnose_fetch_health()` 必须在所有 `summarize()` 调用之后执行**，否则 `_LLM_STAT` 恒为 0、`summary` 档永远不触发。首版把它放在抓取循环后面（读起来更顺），结果恰恰漏掉了当天真实发生的那次余额耗尽——机制建好了却抓不到它本该抓的故障。状态文件 `scripts/fetch_status.json` 是运行时产物，已 gitignore。

> `summary` 档刻意排在最前面判定：这种情况下 `total_items > 0` 看起来一切正常，但页面同样空白，而处理办法（充值）与其他几档截然不同。

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
| 手动补跑（抓新闻 + 日报草稿，一步到位） | 人工触发 | 双击 `抓新闻并发邮件.command`，或 `./scripts/run_manual.sh [日期] [--no-mail]` |
| 启停上面两个定时任务 | 人工触发 | `./scripts/schedule.sh {on\|off\|status}` |
| 日报图片邮件草稿（T-1 日新闻，密送多人，人工确认后手动发送） | 每天 10:10 PKT | 本地 macOS launchd `scripts/com.cmpak.telecom-digest.plist` → `scripts/run_digest.sh` |

> `update-industry` 与 `update-macro` 是同一个 workflow 文件里的两个独立 job，共用同一个 cron，但各自独立 `git add`/`commit`/`push`/建 Issue/发邮件，互不影响、互不阻塞——一个失败不影响另一个正常更新，出问题时也能立刻定位是哪个页面的脚本挂了。两个 job 都在推送前 `git pull --rebase`，避免并发写 `main` 冲突。
>
> 新闻抓取已从 GitHub Actions 迁移到本地 launchd（`update_news.yml` 现仅保留 `workflow_dispatch` 手动触发），因为 DeepSeek Key 改为本地 `scripts/.env.local` 管理，且需要在同一次运行中 `git pull --rebase` + `commit` + `push`。`send_daily_digest.py` 默认读取昨天（T-1）的 `news_cache.json`（实际读取的是 `index.html` 里已经排好序/去重/过滤空摘要的 `NEWS_DATA`，不是直接读 `news_cache.json` 重新计算，见脚本 `load_today_news()` 注释）。**2026-07-13起改为：若 T-1 当天无新增新闻，不再回退到旧日期把旧新闻当日报再发一遍**——此时跳过日报草稿，改为只给本人（`NOTIFY_EMAIL`，收件人栏，不密送 BCC_EMAILS 全员、不带附图）在草稿箱生成一封纯文字提醒邮件（说明当天无新增、最近有数据的日期），同样只 `save` 不 `send`。摘要图片由脚本内建的 HTML 模板渲染（非 `index.html` 截图）。**2026-07-04起改为生成邮件草稿而非自动发送**：通过 AppleScript 把 `scripts/send_daily_digest.py` 里 `BCC_EMAILS` 列表全员放进密送栏，只 `save` 到 Apple Mail 的草稿箱，不调用 `send`——由用户在草稿箱人工确认后手动发送。

> **代理策略（2026-08-12 定）：自动任务永不碰代理，只有手动脚本探测代理。** `scripts/.env.local` 里**刻意不配** `HTTP_PROXY`/`HTTPS_PROXY`——launchd 的自动任务只负责巴基斯坦本地直连的场景，配了反而会在代理没开时整轮失败。人在国内需要代理时，自己先挂好 Clash，再手动跑 `run_manual.sh`（或双击 `抓新闻并发邮件.command`），该脚本探测 `127.0.0.1:7890`，探到就 `export` 给 curl 和 git 一起用，探不到就直连。
>
> 踩过的两个坑，别再退回去：(1) `update_news.py` 内部有"代理不通就降级直连"的逻辑，**但 git 没有**——`.env.local` 一旦配上代理，`source` 它的 shell 脚本里的 `git pull/push` 就会撞死在 127.0.0.1:7890，而同一轮的新闻却抓得好好的，症状极具迷惑性。(2) `git add` **必须带 `scripts/news_update_log.txt`**：它是被跟踪文件、每次运行都变，漏掉它工作区就常年是脏的，下次 `git pull --rebase` 直接罢工（`cannot pull with rebase: You have unstaged changes`），而这个报错只写进 `/tmp/telecom_news_fetch.log`，页面照常更新，很难发现。
>
> **launchd 按本机时区触发**，plist 里没有也设不了固定时区。人在巴基斯坦时 09:30 = 09:30 PKT；回国后 Mac 切到 CST，09:30 CST = 06:30 PKT，巴基斯坦媒体当天还没发稿，新闻会系统性滞后一天（不丢，只是隔天才入库）。回国要么把两个 plist 的 Hour 各 +3，要么 `./scripts/schedule.sh off` 改成全手动。

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
- `is_relevant()` 关键词过滤带**地域校验**（2026-07-12 加）：命中电信/宏观关键词后，若标题明显在讲外国（`_FOREIGN`：Thai/India/China 等国家词，子串匹配；外加 `_FOREIGN_WB`：`us`/`uk`/`eu`/`opec` 等**缩写按整词匹配**——2026-07-16 补，否则 `us` 会误伤 `business`/`focus`）且完全不含巴基斯坦标识（`_PK_MARKERS`：Pakistan/SBP/PTA/Karachi 及四大运营商等）则否掉。因为 `_TELECOM_SUB` 里的宏观词（`central bank`/`inflation rate`/`interest rate`/`monetary policy`…）是全球通用的，而 BusinessRecorder 会转发 Reuters/AFP 的外国新闻（真实事故：泰国"central bank chief"通胀新闻因命中 `central bank` 混进看板；2026-07-16 又发现"Asian stocks gain on drop in US inflation rate"因 `_FOREIGN` 当时不含美式缩写 `US`/`asian stock` 而漏拦——已补 `_FOREIGN_WB` + `asian stock/market`、`wall street`、`us inflation/fed/treasury` 等短语）。这类被 `is_relevant()` 否掉的条目在抓取入口就被拒收。**但不回溯清洗历史缓存**（2026-08-13 用户明确改的）：以前每次运行都拿最新规则把整份 `news_cache.json` 重筛一遍（美其名曰"历史残留自愈清除"），副作用是调一次关键词就可能悄悄抹掉若干条早已展示过的旧新闻，而且改规则必须跑一整轮抓取才生效。现在默认只影响以后抓到的新闻；确实要按新规则清理旧数据时，显式跑 `python3 scripts/update_news.py --reclean`（对应模块级 `RECLEAN_CACHE`，默认 `False`）。反过来，宏观词覆盖也要留意漏收：IMF 相关只列了 `imf program/review/tranche/loan/talks/funding/disbursement/bailout` 这些**相邻短语**，`IMF approves…disbursement` 这种词被隔开的仍匹配不上——发现漏收的正当新闻时优先补 `_TELECOM_SUB` 关键词，别去松动地域校验。
- **休市/放假/停业等例行公告**（2026-08-11 加，直接进 `_EXCLUDE` 无条件排除）：`PSX, SBP to remain closed on August 14`（独立日休市）靠 `sbp` 整词匹配混入，但交易所与银行的节假日安排对电信和宏观都无实质影响。关键词一律用**复合短语**（`remain closed`/`public holiday`/`trading holiday`…），**不能只写 `holiday`**——否则会误伤 `Jazz launches new holiday package` 这类漫游/节日资费套餐新闻。
- **六类定向排除（用户指定）**，都在 `is_relevant()` 开头、关键词匹配**之前**判定，且都带"例外"机制，避免把有价值的监管新闻一起砍掉。除燃油那类外，例外统一是"标题含 `_TELECOM_ENTITY`"：
  1. **非电信口的人事任命**（`_is_finance_appointment()`）：`Govt Appoints Muhammad Ali Malik as SBP Deputy Governor` 靠 `_TELECOM_WB` 里的 `sbp` 混进来，但金融系统高管履新与通信行业无关。命中 `_APPOINTMENT`（appoint / named as / sworn in / board of governors…）且标题**不含** `_TELECOM_ENTITY`（pta/telecom/jazz/zong/ufone/telenor/ptcl/spectrum/frequency…）才排除——所以"PTA 任命新主席"、"PTCL 高管进 PSTD 理事会"仍收得到。**刻意只排任命、不排辞职/免职**：央行行长突然去职属重大宏观变故，与常规履新不是一回事，`resign`/`steps down` 不在 `_APPOINTMENT` 里。
  2. **次要运营商自身动态**（`_is_minor_operator_only()`）：`WorldCall Telecom Completes Capital Reduction and Stock Split` 这类中小固网/宽带/军方运营商的财务重组、产品发布不影响竞争格局。`_MINOR_OPERATORS`（worldcall/wateen/nayatel/transworld/multinet/cybernet/stormfiber/supernet/optix/airlink）子串匹配 + `_MINOR_OPERATORS_WB`（sco/nrtc）整词匹配，命中后还要标题**不含** `_MAJOR_PLAYERS`（四大运营商 + PTA/SBP/MoITT/CCP/govt/court/regulator）才排除——所以"PTA 处罚 WorldCall"这类监管动作照收。注意 `airlink` 原本在 `_TELECOM_SUB` 里，现由此规则拦下其自身业务新闻（该公司实为手机分销商，历史条目多是 HVAC 合同、电动车组装厂这类无关内容）。
  3. **单家金融机构的经营/监管动态**（`_is_single_finance_firm_news()`，2026-08-13 加银行、2026-08-19 扩到兑换商）：只保留宏观经济环境类新闻——SBP 的货币政策、利率、储备、汇率照收，但个体机构的事不收。两个触发案例：`Standard Chartered CEO to assume charge after SBP clearance`（靠 `sbp` 混入，且 `assume` 与 `charge` 间隔四个词，`_APPOINTMENT` 的短语匹配够不着）；`SBP cancels licence of exchange company`（用户 2026-08-19 指定排除——这类稿 SBP 几乎每月发、各媒体齐发，库里一次攒了 6 条）。`_COMMERCIAL_BANKS`（standard chartered / habib bank / meezan bank…）与 `_FOREX_DEALERS`（exchange company / exchange firm / money changer / currency dealer…）子串匹配 + `_COMMERCIAL_BANKS_WB`（hbl/ubl/mcb/abl/bop/nbp…）**整词**匹配——缩写用子串会灾难性误伤：`ubl` 命中 p**ubl**ic（public holiday / public sector）、`abl` 命中 avail**abl**e / t**abl**e / st**abl**e。**`_FOREX_DEALERS` 每个词都必须带 company/firm/changer/dealer 限定**，只写 `exchange` 会直接毁掉汇率新闻——`exchange rate` 是本看板核心宏观指标之一。例外是电信实体，所以 `PTCL to acquire Easypaisa from Telenor Microfinance Bank` 照收。
  4. **股市行情**（`_is_stock_market()`，2026-08-15 加）：用户明确**以后都不收，不分涨跌幅大小**。触发案例 `PSX closes lower as geopolitical uncertainty weighs`——靠 `_PK_MARKERS_WEAK` 里的 `psx` 当弱标识、又命中 `_GEO_MACRO` 的地缘词进来的。**与燃油那条的分流方式刻意不同**：油价大幅调整是通胀先行指标要留，股市指数涨跌不直接传导到物价，所以一律不收。`_STOCK_MARKET` 全是复合短语（`psx closes`/`kse-100`/`stocks close`/`trading session`…），`_STOCK_MARKET_WB` 只有整词 `bourse`——**不能只写 `stocks`/`shares`/`index`/`market`**，会误伤 `Pakistan's telecom market grows`、`PTA releases market share data`。例外是电信实体，所以 `PTCL shares surge after merger approval` 仍收得到。
  5. **例行燃油调价**（`_is_routine_fuel_price()`）：巴基斯坦每半月调一次油价，`OGRA Announces New Petrol & Diesel Prices for Today` 会反复刷屏；但**大幅**调整是通胀先行指标，要留。判据是**标题里有没有写出调整幅度**——媒体报大幅调价必然把数字放进标题（`hiked by Rs15 per litre`），例行公告只说"新价格已公布"。命中 `_FUEL_PRICE_HINT` 后，幅度 ≥ `FUEL_BIG_MOVE_RS`(10 卢比/升) 或 `FUEL_BIG_MOVE_PCT`(5%) 就放行。**刻意只认 `by Rs<n>` / `<n>pc` 这类变动幅度，不认绝对价格**：`Petrol price now Rs280 per litre` 里的 280 是价位不是涨幅，仍属例行播报。
  6. **银行业审慎监管细则**（`_is_bank_regulation()`，2026-08-22 加）：SBP 面向银行发的贷款成数、还款能力、抵押估值、贷款期限这类操作性规章，属金融行业内部规则，对电信没有传导。触发案例 `SBP Allows Banks to Finance Up to 90% of Property Value`、`SBP extends housing loan tenor to 30 years`。**分界线是"宏观环境收、操作细则不收"**——政策利率、外汇储备、通胀、汇率、经常账户照收，二者都挂 SBP 的名，靠 `_BANK_REGULATION` 这组词区分。用 `property value` 而**不是**裸 `property`：电信法路权新闻满篇 `property owner`（`Govt Revises Telecom Bill to Require Property Owner's Consent`），裸词会误伤——虽然那些标题带 telecom 能被电信实体例外救回，但不该依赖第二道闸。例外同样是电信实体，所以 `Jazz International Completes Rs. 4.15 Billion Acquisition of TPL Insurance`（电信企业收购保险公司）不受影响。
- **地缘政治 → 输入性通胀（`_GEO_MACRO`，2026-08-11 加）**：看板要的是"外部冲击如何推高巴基斯坦物价/汇率/进口成本"，不是国际大宗行情本身。它是一条**附加的**通过路径（`matched or geo_ok`），不改动原有匹配；但命中后**无条件**要求标题带 `_PK_MARKERS`，比 `_FOREIGN` 那道闸更严（那道只在出现外国词时才要求）。于是 `Oil price surge pushes Pakistan inflation higher` 收，`Middle East conflict sends crude to $100` 不收。

  > **教训（当天就踩到）**：首版把 `freight` 和 `sanction` 直接写进 `_GEO_MACRO`，重跑立刻误收 `Russia and Pakistan to Launch First Direct Freight Rail Service`——中俄巴货运铁路是地缘经济新闻，但与通胀无关，且旧规则本来收不到（标题无任何电信/宏观词）。已收窄为 `freight cost`/`freight rate`（只有**运费**上涨才是通胀传导），`sanction` 改复数 `sanctions`（单数会误伤 `ECC sanctioned Rs5bn…` 的"核准"义项）。**往 `_GEO_MACRO` 加词必须是复合短语**，单个通用名词一定会漏进无关新闻——与 `_DEDUP_STOP` 那条"稀有词必须是专名"同源。
  >
  > 改 `is_relevant()` 后**先拿全库标题跑回归再重跑抓取**：`json.load(news_cache.json)` 逐条过 `is_relevant()`，列出将被剔除的条目人工过目一遍。这次 402 条里剔除 14 条，除用户点名的 4 条外，另有 7 条小运营商业务动态、1 条 HBL/上合组织（此 SCO 非彼 SCO，碰巧拦对）、2 条 SCO 审计违规（`Audit Uncovers Rs9 Billion in Irregularities in SCO Operations`、`AGP Flags Rs. 885 Million Irregularities In SCO Data Center Project` —— 事件本身有分量，但主体是边缘运营商，**已向用户确认随大类剔除、不设例外**，不要再往 `_MAJOR_PLAYERS` 补 `audit`/`agp` 把它们放回来）。
- 新闻源优先级（高→低，即 `SOURCE_PRIORITY`，同时也是 `_GN_ALLOWED_PUBLISHERS` 白名单）：PTA（自 2026-08-13 起指 pta.gov.pk 官方原文）> ProPakistani > SBP > Dawn > BusinessRecorder > TechJuice，同日相似标题会去重（保留排序更靠前的一条，即重要性更高、来源优先级更高的）。Dawn 于2026-07-19加入（`fetch_dawn()`，Business RSS），排在 BusinessRecorder 之前——巴基斯坦英文报纸中的权威大报，但电信稿量小，`is_relevant()` 过滤后每次通常只有个位数条目。PhoneWorld 已于2026-07-02因质量问题（会把过时新闻当新内容重新发布）被 Business Recorder 替换，**2026-07-19 起彻底移除**：配色常量、`news_cache.json` 与 `index.html` 里残留的2条历史条目一并删除（`industry_index.html` 的 QoS 历史排名出处引用保留，那是对既有报道的事实标注，不是新闻源配置）。
- `fetch_google_news()` 过去**不做 `is_relevant()` 过滤**（其他所有 fetcher 都做），不相关标题会一路走到 `summarize()`，白烧一次 DeepSeek 调用，最后才被入库前的全量回扫剔掉——2026-07-19 的一次运行里 10 条新条目有 6 条如此。已在该函数内补上过滤，最终缓存内容不变，只是不再浪费调用。
- Dawn 和 Business Recorder 都是**综合财经 RSS**（`fetch_rss_feed()` 共用解析），不是电信垂直源，大部分条目与看板无关且都会转发 Reuters/AFP 的外国新闻，因此 `is_relevant()` 的地域校验对这两家尤其关键（见上一条）。新增同类 RSS 源时直接复用 `fetch_rss_feed(feed_url, source_label, display_name)`，不要再复制一份解析逻辑。
- **摘要只做内容转述，不做评价**（2026-08-14 用户明确，改 `summarize()` 的 prompt 时勿退回）：此前要求写 2 段、第 2 段是"对电信行业或宏观经济的影响与判断"，产出的多是"属于企业社会责任范畴，重要性较低""不会改变市场竞争态势"这类空泛套话，占一半篇幅却不提供信息。现在**不分段**，只写谁、何时、做了什么、涉及哪些数字与机构、当事方怎么说；影响分析/意义评价/前景展望/元描述一律禁止。**篇幅按素材给，两头都要在 prompt 里讲明**：有正文时写满 200～300 字并转述细节，只有标题时据实写短（五六十字也可以）——写死字数会让抓不到正文的条目拿评述凑篇幅（恰是本次要去掉的东西），只说"可以写短"则有正文的条目会缩到一百来字丢掉细节；title-only 降级分支另外重申一次禁令，模型在信息不足时格外容易靠评述灌水。字数上限是软约束，招标细则这类信息密集的新闻仍会写到 400 字上下。`importance` 字段照常判定（排序和每日配额要用），但**只存字段、不写进正文**。重点标注（`【】`，U+3010/U+3011）改为全文 2～3 处。历史摘要不重新生成，只对以后抓取的新闻生效。
- 新闻重要性分级：`summarize()` 让 DeepSeek 在生成摘要的同时判定"高/中/低"，标准是 (1) 是否涉及四大主流运营商（Jazz/Zong/Telenor/Ufone）或SBP/PTA监管动作，完全不涉及（如中小ISP、SCO等边缘运营商）判"低"；(2) 即使涉及主流运营商/监管机构，若只是常规新闻（非监管处罚/并购/财报/重大政策）也判"中"而非"高"。每日展示时PTA标题新闻优先前置（封顶`MAX_PTA_PER_DAY`5条），同级再按重要性、来源排序，"低"重要性新闻常因当天候选超过展示上限（`MAX_PER_DAY`8条，或来源不够3个时降级为`LOW_DIVERSITY_CAP`5条）被挤出展示，但仍完整保留在 `news_cache.json` 里。旧缓存中没有 `importance` 字段的条目不会被批量回填，排序时按"中"处理。
- 标题含"PTA"的新闻在每日展示中优先前置，但封顶 `MAX_PTA_PER_DAY`（2026-08-13 从 3 提到 5：修好 Google News 取数后 PTA 源恢复正常，8-12 那天有 9 条 PTA 候选却只排上 2 条；每日总数仍是 `MAX_PER_DAY`(8)，所以最多占 5 席、至少给其他来源留 3 席），避免PTA新闻多的时候把其他来源全部挤掉；超出封顶的PTA新闻会和非PTA新闻放在一起按重要性/来源优先级重新竞争剩余名额。
- 跨源同事件去重是**三层**（都只处理最近 `DEDUP_LOOKBACK_DAYS`(3天)内的新闻；第1、2层作用于整个窗口即**跨天**，第3层仍逐天；同一事件保留**日期更早**的一条——即昨天已展示过的那条，今天重复的那条被标记去掉，符合"当天和前一天比对去重"）：
  1. **`mark_duplicates()` 确定性实体重叠去重（唯一持久化的一层，跨天）**：把最近 `DEDUP_LOOKBACK_DAYS` 天的候选**汇成一个池**（而非逐天），提取标题里窗口内低频的显著词（人名/机构缩写等，出现文档数 ≤ `ENTITY_RARE_DF_MAX`，排除 Ufone/Telenor/merger 这类高频话题词），两条共享的稀有词 ≥ `ENTITY_OVERLAP_MIN_RARE`(3) 即判为同一事件，给日期更晚的一条写 `dup_of`（保留条即较早那条的url）存进 `news_cache.json`。df 按整窗口算，所以跨多天共现的话题词自然变高频被排除，跨天阈值和原来逐天一样保守，绝不会把滚动事件的不同进展误合并。**决策一旦落盘就固定**，展示时直接跳过 `dup_of` 条目——防止"已去重的新闻下次又冒出来"。幂等：重复运行结果一致，已标记的不复算。
  2. **`llm_dedup_groups()` LLM语义去重（当次展示用，不持久化，跨天）**：对最近 `DEDUP_LOOKBACK_DAYS` 天窗口**整体跑一次**（非逐天），用DeepSeek识别措辞差异大、实体兜底抓不到的**跨天同事件重复**——这正是常见的跨天重复形态（不同媒体隔天用不同措辞报同一事件，共享稀有词 < 3，确定性层抓不到，只有LLM能识别；例如 TechJuice "PTA Fines Jazz, Zong, Ufone and Telenor Rs740 Million" 与次日 BusinessRecorder "PTA imposes Rs740m penalties on four cellular mobile operators"）。保留较早一天、去掉较晚一天，只过滤当次展示。**刻意不持久化**：DeepSeek 即使 `temperature=0` 也非确定性，且偶尔会把同话题不同角度的新闻（如合并后的"资费上涨"vs"员工裁员"vs"暂停改名"）**过度合并**成一条——跨天窗口更容易踩到这种误判，若落盘会永久误删不同新闻，所以只让它影响单次展示、下次自我纠正。
  3. **字符串近似去重（逐天）**：兜底同一天标题字面几乎相同的残留。

  > **2026-07-22 重要修订：去重不再只看标题。** 原先三层的输入全是标题，于是两家媒体从不同角度给同一新闻起标题时，三层集体失效。真实案例：ProPakistani "Pakistan Gives Telcos New Spectrum for Faster 5G Rollout" 与 TechJuice "New 5G Rules Push Telecom Firms Toward Fiber Expansion" 标题相似度仅 **18%**（主体/动作/对象全不同，判成两件事在标题层面是**正确**的），但摘要相似度 59% 且引用同一组数字（E-Band频谱、3月拍卖480 MHz、光纤化率17.9%、Jazz 22%/Zong 19%/Telenor 16%/Ufone 9%）——**同一性只在正文里可见**。现 `llm_dedup_groups()` 的每个条目附带 `summary_zh` 前 `DEDUP_SUMMARY_CHARS`(100) 字，prompt 明确要求以摘要核心事实为准、标题仅作参考。
  >
  > **随之而来的新风险：报道 vs 驳斥被合并。** 给 LLM 摘要后，它开始把一条新闻和"驳斥该新闻"的新闻并成一条——两者摘要引用同一组数字，内容层面看几乎一样。真实案例（同日）：Dawn "Mobile phone imports top Rs520bn in FY26" 与 ProPakistani "Customs Rejects Claims of Surge in Finished Mobile Phone Imports"，后者正是海关驳斥前者、称统计口径被误读。**这是一条热点新闻的争议双方，最有价值的信息，绝不能合并。** 改 prompt 措辞无效（temperature=0 下重复运行返回同样的错误合并），故在代码里强制：`_split_rebuttal_groups()` 拆掉"一条是反驳、另一条不是"的组；全是反驳则说明多家媒体在报同一个澄清，允许合并。
  >
  > `_is_rebuttal()` 只在**标题**（英文词 reject/denies/refutes/clarifies…）和**摘要前 `REBUTTAL_LEAD_CHARS`(60) 字**（中文词 驳斥/否认/澄清/辟谣/不实/误读）里匹配——反驳型新闻一定在开头亮明立场。曾用全篇摘要匹配，误报严重："PTA 要求运营商采取**纠正**措施"、"议员引用帖子**反驳**"都会中招，前者是常规业务词、后者是新闻内部情节，都不是"对另一篇报道的反驳"。收紧后全库 312 条只命中 6 条，全部为真实的官方澄清/驳斥类新闻。
  >
  > **LLM 分组共有三道拆分守卫**（都在 `llm_dedup_groups()` 之后依次跑，取舍一致——**拆错了不过是多展示一条重复，不拆则可能静默丢掉一条重要新闻**）：
  > 1. `_split_rebuttal_groups()`——报道 vs 驳斥（见上）。
  > 2. `_split_importance_mismatch_groups()`（2026-08-13 加）——组内 `importance` 不一致**且混有"高"**时拆开。同一事件的两篇报道分量应当相同（实测 PTA 罚 Zong、DIRBS 升级跨天两组都各自一致），所以不一致本身就是"这压根不是同一件事"的信号。事故：Dawn《Regional war drives global food inflation, poses risks for Pakistan》（"高"）被并进前一天 Dawn《SBP warns of price spirals due to geopolitical developments in Middle East》（"中"）——一条是 SBP 货币政策报告、一条是战争对全球粮价的专题分析，结果当天分量最重的一条被静默丢掉，日报也跟着少了。
  > 3. `_split_disconnected_groups()`（2026-08-13 加）——组内按 `_strong_link` 建图取**连通分量**再拆。
  >
  >    **2026-08-15 修：实体比对窗口从摘要前 100 字放开到整篇。** `DEDUP_SUMMARY_CHARS`(100) 本是给 `llm_dedup_groups()` 控 prompt token 用的，被 `_dedup_entity_tokens()` 顺手借用当比对窗口，结果同事件两条新闻的共同证据全落在 100 字以外，这道守卫把 LLM **已经正确合并**的组又拆开了。事故：8-14《SBP governor vows focus on stability》与 8-15《State Bank Says Current Interest Rate is Right》是同一位行长的同一批数字，前 100 字的交集只剩一个 `sbp`，而 `sbp` 恰在 `_LINK_GENERIC` 里被剔除 → 交集为空 → 判成两件事，日报里同一条新闻连着两天出现。放开到整篇后两条共享 `prism`/`410`/`184`/`440`/`210`，正常连通。**注意：机构别名归一化（State Bank → SBP）对这类案例无效**——归一化后仍是 `sbp`，照样被剔除，能救回来的只有摘要正文里的数字和专名。
  >
  >    **但这只修好了"LLM 判对却被拆开"，管不了"LLM 这次没判出来"。** 同一天两轮实测：18:02 那轮 LLM 正确合并了上述三条，23:33 那轮**直接没分组**（`temperature=0` 也不保证跨调用一致，文档开头就记着这个）。另外两层也接不住这一例——`entity_overlap_groups()`（持久化那层）**只看标题**，而两条标题一个写 `SBP` 一个写 `State Bank`，共同词几乎为零；`_strong_link()` 只在 LLM 已分好组后用于拆分，不分组就轮不到它。这次是人工确认后直接给 `dup_of` 落盘处理的。
  >
  >    > **走不通的路，别再试：给"实体高度重叠"加一层确定性合并。** 思路是用 `_dedup_entity_tokens` 的重叠数主动建组补 LLM 漏判，实现后全库压力测试立刻否决——395 条里形成 35 组、要丢 68 条（**17.2%**），把「MoITT&CCP 争议」「PTA 罚 Zong 1.167 亿」「MVNO 牌照」「法院转移 Telenor 资产」7 条毫不相干的新闻并成一组。量化后边界窄得没法用：**该合并的那对共享 7–8 个实体、重叠率 0.58–0.67；不该合并的那些共享 5–6 个、重叠率 0.31–0.50**，中间只隔 0.08。根因是中文摘要里能被 `[a-z0-9]+` 提取的只有数字和零星英文专名，同话题新闻天然共享一批金额和运营商名，**区分不了"同一事件"和"同一话题"**。同样的判据用来**拆**（`_strong_link`）没问题——拆错只多展示一条；用来**合**就是静默丢新闻，两者的错误代价不对称。
  >
  >    配套把**财年/年份**（`fy24`–`fy28`、`2024`–`2028`）加进 `_LINK_GENERIC`：窗口一放开，这类时间标签立刻成了高频"共同实体"，实测上面那条**必须拆开**的案例（`Regional war drives global food inflation` vs `SBP warns of price spirals`）就是只靠 `fy26`/`fy27` 连上的。它们和 `sbp` 一样是背景板，不是事件标识。往 `_LINK_GENERIC` 加词的判准：**这个词是不是几乎每条同类新闻都有**——是就加。候选变多后（接入 PTA/SBP 两个 Google News 源，单日候选从个位数涨到 19 条）LLM 开始把不相干的新闻并进一组。事故：《Pakistan Government Considers Abolishing Mobile Phone Taxes》保留，而三条 PTA 罚 CM Pak/Zong 7780 万卢比的新闻被当作重复丢弃——**与本公司直接相关的处罚新闻整个从看板消失**。拆后成 {取消手机税} 和 {三条罚款} 两组，罚款仍正确合并成一条。
  >
  > **同期修订 `_DEDUP_STOP`**：确定性层（第1层）曾把上述 Dawn 报道与海关驳斥合并并**持久化**（共享 `mobile`/`phone`/`imports` 恰好 3 个词，达标），静默删掉了原始报道。根因是这些**通用行业名词**在 3 天窗口里碰巧低频（df ≤ `ENTITY_RARE_DF_MAX`），被当成了本该是人名/机构缩写的"高信号实体"。已把 mobile/phone/imports/telecom/spectrum/users/tariff/operators 等一批通用词加入停用表；显著数字（rs740m、900000）和专名不受影响。回归验证：历史 12 组正确合并中 11 组仍由确定性层保持，2 组降到门槛以下改由 LLM 层负责（其中 PTA Rs740m 那组本就是文档中注明"只有LLM能识别"的案例）。
  >
  > **教训**：确定性层的"稀有词"必须是**专名**，不能是碰巧低频的普通名词——它一旦误判就是持久化的、静默的数据删除。给 LLM 更多上下文会提升召回，但也会带来新的过度合并形态，每次扩充输入都要问一句"这会让它把哪些本不该合并的东西合并掉"。
  > 背景（2026-07-07）：曾出现 ProPakistani"PTCL's Chief People Officer Umer Farid Joins PSTD Board of Governors"与 TechJuice"PTCL CPO Umer Farid Appointed to PSTD Board of Governors"同日重复展示——两条明明同事件，但那次运行 DeepSeek 漏判了（temp=0 也不保证跨调用一致）。加确定性实体兜底(层1)+持久化正是为根治这类"LLM间歇性漏判导致重复反复出现"。
