#!/bin/bash
# 每日自动执行：生成图片 → 发送 T-1 邮件
# 由 launchd 在每天 10:10 PKT 自动触发（新闻已由 09:30 的 fetch 任务抓好）

PROJECT="/Users/huwenxiao/Downloads/For Claude/pta-telecom-dashboard"
LOG="/tmp/telecom_digest.log"

echo "=== $(date '+%Y-%m-%d %H:%M:%S') 开始执行 ===" >> "$LOG"

cd "$PROJECT" || exit 1

# 生成图片并发邮件
python3 scripts/send_daily_digest.py >> "$LOG" 2>&1

echo "=== 执行结束 ===" >> "$LOG"
