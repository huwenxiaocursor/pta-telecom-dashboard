#!/bin/bash
# 每周四 15:00 由 launchd 触发：生成"宣传信息填报提醒"邮件草稿。
# 只写草稿箱，不发送——发送由人在 Mail 里手动确认。

PROJECT="/Users/huwenxiao/Downloads/For Claude/pta-telecom-dashboard"
LOG="/tmp/weekly_publicity.log"

echo "=== $(date '+%Y-%m-%d %H:%M:%S') 开始执行 ===" >> "$LOG"

cd "$PROJECT" || exit 1
python3 scripts/weekly_publicity_reminder.py >> "$LOG" 2>&1

echo "=== 执行结束 ===" >> "$LOG"
