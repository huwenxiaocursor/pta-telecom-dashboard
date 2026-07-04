# Pakistan Telecom & Economy Intelligence Hub

巴基斯坦电信与宏观经济实时信息看板，数据自动抓取、每日更新，通过 GitHub Pages 公开访问。

**线上地址：** https://huwenxiaocursor.github.io/pta-telecom-dashboard/

---

## 功能模块

### 1. 电信行业数据看板（`index.html`）
- 移动用户数月度趋势（含 YoY 对比）
- 运营商市场份额对比（Jazz / Zong / Telenor / Ufone）
- PTA 季度 QoS 报告（城市网络质量评分）
- KPI 卡片：总用户、3G/4G 用户、宽带、数据用量、渗透率

### 2. 宏观经济数据看板（`macro_index.html`）
- 利率、外汇储备、银行间汇率、侨汇、CPI：自动抓取更新（每月10日、25日）
- GDP、财政、产业结构、贸易：人工维护，随《Pakistan Economic Survey》等年度报告更新
- 历史数据永久保留于 `scripts/macro_history.json`，图表按滚动窗口展示最近若干期

### 3. 通信行业新闻聚合（`index.html` 新闻区）
- 来源：PTA 官网、ProPakistani、SBP、Business Recorder、TechJuice
- 每日展示上限随当天渠道多样性动态调整：候选覆盖≥3个不同来源时上限8条，否则降为5条（避免一两家媒体的产出把当日新闻栏"撑满"）；PTA标题新闻优先前置（封顶3条），同级再按重要性、媒体优先级排序（PTA > ProPakistani > SBP > BusinessRecorder > TechJuice）
- AI 自动生成 200-300 字中文摘要（DeepSeek Chat API，基于抓取到的正文，无正文时退回title-only安全模式）+ 高/中/低重要性分级
- 相关性过滤：仅保留电信、移动网络、宏观经济、IMF 相关内容
- 同一事件跨来源去重（近3天，DeepSeek判定）

### 4. 每日邮件摘要（`scripts/send_daily_digest.py`）
- 每天 10:10 PKT 自动生成 T-1（昨天）新闻高清图片（960px，3× 分辨率）
- 通过 macOS Apple Mail 生成邮件草稿，18人名单全部放在密送栏，不自动发送——保存到草稿箱，由人工确认后手动发送
- 由 macOS `launchd` 调度，无需手动干预；依赖 09:30 的新闻抓取任务先完成

### 5. Zong 套餐清单（`zong_packages_index.html`）
- 预付费/后付费全套餐价格与内容，支持搜索与分类筛选（后付费/预付费/综合/流量/通话短信/应用专属/增值服务）
- 数据来自 zong.com.pk（2026年6月采集），纯静态手工维护，不接入自动化管线

---

## 文件结构

```
├── index.html                          # 主看板页面（单文件，含图表+新闻）
├── industry_index.html                 # 行业数据子页
├── macro_index.html                    # 宏观经济子页
├── zong_packages_index.html            # Zong 套餐清单（纯手工维护）
├── scripts/
│   ├── update_pta_dashboard.py              # 抓取 PTA 月度用户/市场份额数据
│   ├── update_macro_dashboard.py            # 抓取宏观数据：利率/储备/汇率/侨汇/CPI
│   ├── update_news.py                       # 抓取五大来源新闻 + 生成中文摘要
│   ├── send_daily_digest.py                 # 生成日报图片并发送邮件（T-1 日新闻）
│   ├── run_news_fetch.sh                    # 新闻抓取定时任务入口脚本（含 git pull/commit/push）
│   ├── run_digest.sh                        # 每日摘要定时任务入口脚本
│   ├── run_update.sh                        # PTA 数据更新入口脚本
│   ├── com.cmpak.telecom-news-fetch.plist   # macOS launchd 配置（每天 09:30 PKT 触发新闻抓取）
│   ├── com.cmpak.telecom-digest.plist       # macOS launchd 配置（每天 10:10 PKT 触发日报邮件）
│   ├── .env.local                           # 本地 DEEPSEEK_API_KEY（已 gitignore，不提交）
│   ├── news_cache.json                      # 新闻缓存（含中文摘要）
│   ├── history_monthly.json                 # PTA 月度历史数据（2025-01 起）
│   ├── macro_history.json                   # 宏观数据永久历史（只增不覆盖，供回溯）
│   ├── macro_known_fy.json                  # 记录已知最新 Economic Survey 财年
│   ├── update_log.txt                       # PTA 数据更新日志
│   ├── macro_update_log.txt                 # 宏观数据更新日志
│   └── news_update_log.txt                  # 新闻抓取日志
├── .github/workflows/
│   ├── update.yml                      # GitHub Actions：每月 10、25 日 10:00 PKT 自动更新 PTA + 宏观数据（两个独立 job）
│   └── update_news.yml                 # GitHub Actions：新闻抓取（现仅 workflow_dispatch 手动触发，日常抓取已迁移至本地 launchd）
```

---

## 自动化机制

| 任务 | 触发时间 | 方式 |
|------|----------|------|
| PTA 电信数据更新 | 每月 10、25 日 10:00 PKT | GitHub Actions（`update.yml` → `update-industry` job） |
| 宏观经济数据更新 | 每月 10、25 日 10:00 PKT | GitHub Actions（`update.yml` → `update-macro` job） |
| 抓取新闻 + 生成摘要 + commit/push | 每天 09:30 PKT | 本地 macOS launchd（`run_news_fetch.sh`） |
| 生成日报图片邮件草稿（T-1 日新闻，待人工确认发送） | 每天 10:10 PKT | 本地 macOS launchd（`run_digest.sh`） |

> PTA 电信数据与宏观经济数据是同一个 workflow 文件里的两个独立 job，共用同一个 cron 触发时间，但各自独立提交/通知，一个失败不影响另一个。宏观数据中 GDP/财政/产业结构/贸易不参与自动化，人工维护（详见 `CLAUDE.md`「宏观年度数据维护」）。
>
> 新闻抓取原先由 GitHub Actions 每晚触发，现已迁移到本地 launchd：DeepSeek Key 改为本地 `scripts/.env.local` 管理，且需要在同一次运行中完成 `git pull --rebase` + commit + push。GitHub Actions 侧的 `update_news.yml` 仅保留手动触发（`workflow_dispatch`）作为备用。

---

## 本地安装自动化任务

```bash
# 1. 配置本地 DeepSeek Key（新闻抓取任务需要）
echo 'DEEPSEEK_API_KEY=<key>' > scripts/.env.local

# 2. 安装两个 launchd 定时任务
chmod +x scripts/run_news_fetch.sh scripts/run_digest.sh
cp scripts/com.cmpak.telecom-news-fetch.plist scripts/com.cmpak.telecom-digest.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.cmpak.telecom-news-fetch.plist
launchctl load ~/Library/LaunchAgents/com.cmpak.telecom-digest.plist

# 3. 验证
launchctl list | grep cmpak

# 4. 手动测试（可选）
python3 scripts/update_news.py
python3 scripts/send_daily_digest.py
```

日志位置：`/tmp/telecom_news_fetch.log`（新闻抓取）、`/tmp/telecom_digest.log`（日报邮件）

---

## 依赖

- Python 3.11+
- `playwright`（截图生成）：`pip install playwright && playwright install chromium`
- `requests`（HTTP 抓取）
- `pymupdf`（PDF 文字提取，宏观数据 CPI 抓取用）、`openpyxl`（Excel 解析，宏观数据侨汇抓取用）
- DeepSeek API Key（GitHub Actions 存于 Secrets `DEEPSEEK_API_KEY`；本地 launchd 任务存于 `scripts/.env.local`，已 gitignore；同时用于新闻摘要生成和宏观数据 CPI 结构化抽取）
- macOS Apple Mail（邮件发送）

---

## 数据来源

### 新闻聚合

| 来源 | 内容 | 抓取方式 |
|------|------|----------|
| [PTA](https://www.pta.gov.pk) | 官方公告、监管动态 | Google News RSS |
| [ProPakistani](https://propakistani.pk) | 电信/科技新闻 | WordPress REST API |
| [SBP](https://www.sbp.org.pk) | 货币政策、外汇储备 | Google News RSS |
| [Business Recorder](https://www.brecorder.com) | 财经/商业新闻（巴基斯坦最悠久财经日报） | RSS |
| [TechJuice](https://www.techjuice.pk) | 科技行业动态 | WordPress REST API |

### 宏观经济数据

| 来源 | 内容 | 抓取方式 |
|------|------|----------|
| [SBP war-current.asp](https://www.sbp.org.pk/ecodata/rates/war/war-current.asp) | 政策利率、外汇储备、银行间汇率 | 正则解析静态 HTML |
| [SBP Homeremit_Arch.xlsx](https://www.sbp.org.pk/assets/document/Homeremit_Arch.xlsx) | 侨汇（按国别） | openpyxl 解析 Excel |
| [PBS Monthly Review PDF](https://www.pbs.gov.pk/price-statistics/) | CPI（全国/城市/农村/SPI） | PyMuPDF 文字提取 + DeepSeek 结构化抽取 |
| [Ministry of Finance Economic Survey](https://www.finance.gov.pk/survey_archieve.html) | GDP、财政、产业结构（人工维护，仅做新报告检测提醒） | 正则检测新财年 |

---

*负责人：胡文潇，CMPak战略部*
