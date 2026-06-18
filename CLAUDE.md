# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目简介
巴基斯坦电信行业数据 Dashboard（PTA 数据看板），自动抓取 PTA 网站数据，生成单页面 HTML 展示。

**线上地址**：https://huwenxiaocursor.github.io/pta-telecom-dashboard/
**GitHub 仓库**：https://github.com/huwenxiaocursor/pta-telecom-dashboard

## 文件结构
- `index.html`：单文件 Dashboard（Chart.js 图表，所有数据内嵌为 JS 常量）
- `scripts/update_pta_dashboard.py`：月度数据更新脚本
- `scripts/history_monthly.json`：月度历史数据累积存储（2025-01 起）
- `scripts/update_log.txt`：每次运行日志
- `.github/workflows/update.yml`：GitHub Actions 自动化（每月1日运行）

## 运行更新脚本
```bash
cd scripts
python3 update_pta_dashboard.py
```
脚本会抓取 PTA 网站最新数据，更新 `history_monthly.json` 和 `index.html` 中的 JS 常量。

## 数据更新机制
- **数据源**：PTA 官网（pta.gov.pk），Highcharts 内嵌数据直接正则提取
- **历史存储**：`history_monthly.json` 永久保存 2025-01 起的月度数据，PTA 只保留滚动12个月，脚本合并新数据不覆盖旧数据
- **JS 常量替换**：`index.html` 中用 `// ===AUTO-NEW-DATA-START===` / `// ===AUTO-NEW-DATA-END===` 标记注入区域
- **`rebuild_months_from_history(n_months=17)`**：从 history_monthly.json 取最近17个月数据重建趋势图

## 自动化（GitHub Actions）
`.github/workflows/update.yml` 每月1日 09:07 PKT 自动运行：
1. 执行 `update_pta_dashboard.py`
2. 若有数据变化，提交推送
3. 创建 GitHub Issue 通知更新内容
4. 发邮件到 shawn.hwx@gmail.com（需配置 `GMAIL_USERNAME` / `GMAIL_APP_PASSWORD` Secrets）

## index.html 图表说明
- **KPI 卡片**（5列）：总用户数、3G/4G用户、宽带用户、数据用量、电话渗透率
- **月度移动用户数趋势**：当年12个月横轴，当年实线 + 去年虚线（YoY对比），当月蓝色高亮 + YoY%标注
- **市场份额对比**：当月 vs 2025年12月分组柱状图（含 ▲/▼ 变化标注）
- **季度 QoS 报告**：从 PTA PDF 提取，表格展示
- **市场份额趋势图**：已隐藏（数据保留，`display:none`）

## 页面标题
"巴基斯坦通信行业数据信息 — 2026"

## 已知问题与注意事项
- PTA 网站结构变化时正则提取会失败，需检查 `update_log.txt` 中的报错
- 2025年1-4月数据已手动补全（PTA 网站已不提供这些月份），不要覆盖
- `history_monthly.json` 是核心数据，误删后历史数据无法从 PTA 恢复
- 手动推送前先 `git pull --rebase`，避免与 Actions 自动提交冲突

## 用户信息
- 负责人：胡文潇，CMPak 战略部副总经理
- 使用场景：每月更新，供内部汇报使用
