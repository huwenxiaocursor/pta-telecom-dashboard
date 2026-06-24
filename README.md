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

### 2. 通信行业新闻聚合（`index.html` 新闻区）
- 来源：PTA 官网、ProPakistani、SBP、PhoneWorld、TechJuice
- 每日最多 5 条，按媒体优先级排序（PTA > ProPakistani > SBP > PhoneWorld > TechJuice）
- AI 自动生成 200-300 字中文摘要（DeepSeek Chat API），重点数据用【】标注
- 相关性过滤：仅保留电信、移动网络、宏观经济、IMF 相关内容

### 3. 每日邮件摘要（`scripts/send_daily_digest.py`）
- 每晚 00:00 自动生成当日新闻高清图片（2880px，3× 分辨率）
- 通过 macOS Apple Mail 发送至指定邮箱
- 由 macOS `launchd` 调度，无需手动干预

---

## 文件结构

```
├── index.html                          # 主看板页面（单文件，含图表+新闻）
├── industry_index.html                 # 行业数据子页
├── macro_index.html                    # 宏观经济子页
├── scripts/
│   ├── update_pta_dashboard.py         # 抓取 PTA 月度用户/市场份额数据
│   ├── update_news.py                  # 抓取五大来源新闻 + 生成中文摘要
│   ├── send_daily_digest.py            # 生成日报图片并发送邮件
│   ├── run_digest.sh                   # 每日摘要定时任务入口脚本
│   ├── com.cmpak.telecom-digest.plist  # macOS launchd 配置（每晚 00:00 触发）
│   ├── news_cache.json                 # 新闻缓存（含中文摘要）
│   ├── history_monthly.json            # PTA 月度历史数据（2025-01 起）
│   └── update_log.txt                  # 数据更新日志
├── .github/workflows/
│   └── update_news.yml                 # GitHub Actions：每晚 23:00 PKT 自动抓取新闻
```

---

## 自动化机制

| 任务 | 触发时间 | 方式 |
|------|----------|------|
| 抓取新闻 + 生成摘要 | 每晚 23:00 PKT | GitHub Actions |
| PTA 月度数据更新 | 每月 1 日 | GitHub Actions |
| 生成日报图片并发邮件 | 每晚 00:00 PKT | macOS launchd |

---

## 本地安装邮件摘要自动化

```bash
# 1. 安装 launchd 定时任务
chmod +x scripts/run_digest.sh
cp scripts/com.cmpak.telecom-digest.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.cmpak.telecom-digest.plist

# 2. 验证
launchctl list | grep cmpak

# 3. 手动测试（可选）
python3 scripts/send_daily_digest.py
```

日志位置：`/tmp/telecom_digest.log`

---

## 依赖

- Python 3.11+
- `playwright`（截图生成）：`pip install playwright && playwright install chromium`
- `requests`（HTTP 抓取）
- DeepSeek API Key（存于 GitHub Secrets `DEEPSEEK_API_KEY`）
- macOS Apple Mail（邮件发送）

---

## 数据来源

| 来源 | 内容 | 抓取方式 |
|------|------|----------|
| [PTA](https://www.pta.gov.pk) | 官方公告、监管动态 | Google News RSS |
| [ProPakistani](https://propakistani.pk) | 电信/科技新闻 | WordPress REST API |
| [SBP](https://www.sbp.org.pk) | 货币政策、外汇储备 | Google News RSS |
| [PhoneWorld](https://phoneworld.com.pk) | 手机/设备资讯 | RSS |
| [TechJuice](https://www.techjuice.pk) | 科技行业动态 | WordPress REST API |

---

*负责人：胡文潇，CMPak战略部*
