#!/bin/bash
# 每日自动执行：拉取最新新闻缓存 → 生成图片 → 发送邮件
# 由 launchd 在每天晚上 24:00（次日 00:00）PKT 自动触发

PROJECT="/Users/huwenxiao/Downloads/For Claude/pta-telecom-dashboard"
LOG="/tmp/telecom_digest.log"

echo "=== $(date '+%Y-%m-%d %H:%M:%S') 开始执行 ===" >> "$LOG"

cd "$PROJECT" || exit 1

# 拉取 GitHub Actions 最新抓取的新闻（每晚 23:00 PKT 更新）
git pull origin main --quiet >> "$LOG" 2>&1

# 生成图片并发邮件
python3 scripts/send_daily_digest.py >> "$LOG" 2>&1

echo "=== 执行结束 ===" >> "$LOG"
