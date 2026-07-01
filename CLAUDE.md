# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目简介

巴基斯坦电信与宏观经济实时信息看板，部署于 GitHub Pages：
https://huwenxiaocursor.github.io/pta-telecom-dashboard/

## 运行脚本

```bash
# 月度 PTA 数据更新（抓取用户数 + 年度指标）
python3 scripts/update_pta_dashboard.py

# 新闻抓取与摘要生成（需设置环境变量，本地可从 scripts/.env.local 加载）
DEEPSEEK_API_KEY=<key> python3 scripts/update_news.py

# 本地日报邮件（T-1 日新闻，需 macOS + Apple Mail + Playwright）
python3 scripts/send_daily_digest.py
```

依赖安装：
```bash
pip install playwright requests
playwright install chromium
```

无测试框架、无 lint/build 步骤——三个页面均为纯静态 HTML，脚本靠运行后检查 `scripts/update_log.txt` / `scripts/news_update_log.txt` 验证效果。

## 三页面架构

| 文件 | 定位 | 更新脚本 |
|------|------|----------|
| `index.html` | 门户页：导航卡片 + 新闻聚合 | `update_news.py` |
| `industry_index.html` | 电信数据：用户趋势、市场份额、QoS | `update_pta_dashboard.py` |
| `macro_index.html` | 宏观经济：GDP、利率、外汇 | 手动维护 |

## JS 数据注入机制

两种 sentinel 标记由脚本自动替换，手动改动这两对标记之间的内容会在下次脚本运行时被覆盖：

**电信数据**（`industry_index.html`，由 `update_pta_dashboard.py` 写入）：
```
// ===AUTO-NEW-DATA-START===
// ===AUTO-NEW-DATA-END===
```
包含：`annualYears`、`revenues`、`investments`、`fdi`、`ngmsYoY`、`dataUsagePbYoY`、`broadbandYoY`、`teledensityYoY` 等年度/月度同比常量。

月度用户数（`const months` 和运营商数组 `Jazz:`、`Ufone:` 等）在 sentinel 块之外，由 regex 直接替换。

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
| 电信数据更新 | 每月1日 09:07 PKT | GitHub Actions `.github/workflows/update.yml` |
| 新闻抓取 + 摘要 + commit/push | 每天 09:30 PKT | 本地 macOS launchd `scripts/com.cmpak.telecom-news-fetch.plist` → `scripts/run_news_fetch.sh` |
| 日报图片邮件（T-1 日新闻） | 每天 10:10 PKT | 本地 macOS launchd `scripts/com.cmpak.telecom-digest.plist` → `scripts/run_digest.sh` |

> 新闻抓取已从 GitHub Actions 迁移到本地 launchd（`update_news.yml` 现仅保留 `workflow_dispatch` 手动触发），因为 DeepSeek Key 改为本地 `scripts/.env.local` 管理，且需要在同一次运行中 `git pull --rebase` + `commit` + `push`。`send_daily_digest.py` 默认读取昨天（T-1）的 `news_cache.json`，若当天新闻尚未抓取会自动回退到最近一次有数据的日期。摘要图片由脚本内建的 HTML 模板渲染（非 `index.html` 截图），通过 AppleScript 调用 Apple Mail 发送至 `huwenxiao@zong.com.pk`。

`update.yml` 在电信数据变更时还会自动创建 GitHub Issue 并发送邮件通知（收件人 `shawn.hwx@gmail.com`）。

CI Secrets（GitHub Actions）：`DEEPSEEK_API_KEY`、`GMAIL_USERNAME`、`GMAIL_APP_PASSWORD`。本地 launchd 任务的 `DEEPSEEK_API_KEY` 从 `scripts/.env.local`（已 gitignore）读取。

## QoS 数据维护（手动）

`update_pta_dashboard.py` 在每次运行后检查 PTA 是否发布新 QoS PDF。若有新 PDF，会写入 `scripts/qos_update_needed.txt` 并记录链接。需人工阅读 PDF，然后手动更新 `industry_index.html` 中的 `qosOverall`、`qosDownload`、`qosUpload`、`qosLatency`、`qosCCR`、`qosCSSR`、`cityWins` 等常量。

`scripts/known_qos_pdfs.json` 记录已处理的 PDF 链接列表，避免重复告警。

## 注意事项

- `history_monthly.json` 中 2025-01 至 2025-04 数据为人工补录，PTA 已无法再提供这些月份数据，禁止覆盖。
- PTA 页面结构变化时正则提取会失败，运行后检查 `scripts/update_log.txt`。
- 本地推送前先 `git pull --rebase`，避免与 GitHub Actions 自动提交冲突。
- 新闻源优先级（高→低）：PTA > ProPakistani > SBP > PhoneWorld > TechJuice，同日相似标题会去重（保留高优先级来源）。
