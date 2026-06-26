#!/bin/bash
# 每天 09:30 PKT 自动触发：抓取新闻 → 生成摘要 → commit + push 到 GitHub
# 由 launchd com.cmpak.telecom-news-fetch 调度

PROJECT="/Users/huwenxiao/Downloads/For Claude/pta-telecom-dashboard"
LOG="/tmp/telecom_news_fetch.log"
SECRETS="$PROJECT/scripts/.env.local"

echo "=== $(date '+%Y-%m-%d %H:%M:%S') 开始执行 ===" >> "$LOG"

cd "$PROJECT" || exit 1

# 加载本地 API Key（文件不存在则跳过，脚本仍可运行但不生成摘要）
if [ -f "$SECRETS" ]; then
    set -a; source "$SECRETS"; set +a
fi

# 拉取远端最新，避免 push 冲突
git pull --rebase origin main --quiet >> "$LOG" 2>&1

# 抓取新闻并生成中文摘要
python3 scripts/update_news.py >> "$LOG" 2>&1

# 有变更则 commit + push
git add index.html scripts/news_cache.json
if ! git diff --cached --quiet; then
    git -c user.name="cmpak-bot" -c user.email="bot@cmpak.local" \
        commit -m "News refresh $(date '+%Y-%m-%d')" >> "$LOG" 2>&1
    git push origin main >> "$LOG" 2>&1
    echo "  已推送至 GitHub" >> "$LOG"
else
    echo "  无新内容，跳过提交" >> "$LOG"
fi

echo "=== 完成 ===" >> "$LOG"
