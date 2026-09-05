#!/bin/bash
# 每天 09:00 PKT 自动触发：抓取新闻 → 生成摘要 → commit + push 到 GitHub
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

# 等网络就绪再干活。09:00 触发时 Mac 常常刚唤醒、Wi-Fi 还没关联上：2026-08-31 与
# 09-01 连续两天，全部来源都报 "Could not resolve host"，一条新闻没抓到，而任务
# 照常跑完、退出码 0，页面显示"无新增"——从外面完全看不出是断网。
#
# 探测间隔与次数是按"抓取必须在 10:10 的日报之前跑完"倒推的：最坏等 15 分钟，
# 09:15 开始抓，仍留 55 分钟余量。Wi-Fi 正常关联只要一两次探测就能通过。
# 等满仍不通也**继续往下跑**——让 update_news.py 的诊断把 network 档写进
# fetch_status.json，日报邮件里才会出现"当时无网络，联网后补跑"的提示；
# 直接 exit 反而会让这封提醒邮件也发不出来。
NET_TRIES=15
NET_WAIT=60
i=1
while [ "$i" -le "$NET_TRIES" ]; do
    if curl -sS -m 10 -o /dev/null https://propakistani.pk 2>/dev/null \
       || curl -sS -m 10 -o /dev/null https://github.com 2>/dev/null; then
        [ "$i" -gt 1 ] && echo "  网络已就绪（第 $i 次探测）" >> "$LOG"
        break
    fi
    if [ "$i" -eq "$NET_TRIES" ]; then
        echo "  !! 等待 $((NET_TRIES * NET_WAIT / 60)) 分钟后网络仍不通，继续执行以便写出故障诊断" >> "$LOG"
    else
        echo "  网络不通，${NET_WAIT}s 后重试（第 $i/$NET_TRIES 次）" >> "$LOG"
        sleep "$NET_WAIT"
    fi
    i=$((i + 1))
done

# 拉取远端最新，避免 push 冲突。失败要显式记一笔：无网络或工作区脏都会让它罢工，
# 而脚本没有 set -e，会若无其事地继续跑下去。
if ! git pull --rebase origin main --quiet >> "$LOG" 2>&1; then
    echo "  !! git pull --rebase 失败（无网络或工作区有未提交改动），继续执行" >> "$LOG"
fi

# 抓取新闻并生成中文摘要
python3 scripts/update_news.py >> "$LOG" 2>&1

# 有变更则 commit + push。**必须带上 news_update_log.txt**：它是被跟踪文件，
# 每次运行都会改，漏掉它工作区就一直是脏的，下次 git pull --rebase 会直接罢工
# （"cannot pull with rebase: You have unstaged changes"，2026-08-12 查实）。
git add index.html scripts/news_cache.json scripts/news_update_log.txt
if ! git diff --cached --quiet; then
    git -c user.name="cmpak-bot" -c user.email="bot@cmpak.local" \
        commit -m "News refresh $(date '+%Y-%m-%d')" >> "$LOG" 2>&1
    # 必须判退出码：push 失败（断网、远端分叉）时若无条件打印"已推送"，日志就在
    # 撒谎。2026-09-01 实际发生：当天 09:00 本机无网络，push 报
    # "Could not resolve host: github.com"，日志却照旧写着"已推送至 GitHub"，
    # 两天的提交就这么静静躺在本地没上去。
    if git push origin main >> "$LOG" 2>&1; then
        echo "  已推送至 GitHub" >> "$LOG"
    else
        echo "  !! 推送失败：已在本地提交但未同步到 GitHub。" >> "$LOG"
        echo "     网络恢复后在项目目录执行 git push origin main 即可补上。" >> "$LOG"
    fi
else
    echo "  无新内容，跳过提交" >> "$LOG"
fi

echo "=== 完成 ===" >> "$LOG"
