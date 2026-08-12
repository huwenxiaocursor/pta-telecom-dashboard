#!/bin/bash
# 手动跑一整轮：抓新闻 → 生成摘要 → 推送 GitHub → 生成日报邮件草稿。
#
# 什么时候用：人在国内、需要挂代理的时候。先把 Clash 打开，再跑这个。
# 本脚本会自己探测代理端口，**探到就用（curl 和 git 都走代理），没探到就直连**，
# 所以在巴基斯坦不挂代理直接跑也是对的。
#
#   ./scripts/run_manual.sh              # 抓新闻 + 生成昨天的日报草稿
#   ./scripts/run_manual.sh 2026-08-10   # 日报改用指定日期（补发用）
#   ./scripts/run_manual.sh --no-mail    # 只抓新闻，不生成邮件
#
# 邮件只存草稿箱、不自动发送，仍需在 Mail 里人工确认后手动发出。

set -u
PROXY_PORT=7890          # Clash 默认；V2Ray 改 1087，Shadowsocks 改 1080

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT" || exit 1

DIGEST_DATE=""
DO_MAIL=1
for arg in "$@"; do
    case "$arg" in
        --no-mail)            DO_MAIL=0 ;;
        [0-9]*-[0-9]*-[0-9]*) DIGEST_DATE="$arg" ;;
        *) echo "未知参数：$arg"; exit 1 ;;
    esac
done

[ -f scripts/.env.local ] && { set -a; source scripts/.env.local; set +a; }

echo "════════════════════════════════════════"
# ── 探测代理 ───────────────────────────────────────────────
if nc -z -G 2 127.0.0.1 "$PROXY_PORT" 2>/dev/null; then
    export HTTP_PROXY="http://127.0.0.1:$PROXY_PORT"
    export HTTPS_PROXY="$HTTP_PROXY"
    export http_proxy="$HTTP_PROXY" https_proxy="$HTTP_PROXY"
    echo "代理　　 ✓ 已挂（127.0.0.1:$PROXY_PORT），抓取与上传都走代理"
else
    unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy
    echo "代理　　 — 未挂，本轮直连"
fi

if curl -s -o /dev/null --max-time 10 https://news.google.com/rss 2>/dev/null; then
    echo "谷歌新闻 ✓ 可达"
else
    echo "谷歌新闻 ✗ 不可达 —— 两个主源会抓空，只剩巴基斯坦本地媒体"
    echo "         （在国内的话：先打开 Clash 再重跑）"
fi
echo "════════════════════════════════════════"
echo

# ── 抓新闻 ─────────────────────────────────────────────────
echo "▸ 抓取新闻并生成摘要…"
git pull --rebase origin main --quiet 2>/dev/null || echo "  （git pull 跳过，继续本地更新）"
python3 scripts/update_news.py || { echo "✗ 抓取失败，中止"; exit 1; }

# news_update_log.txt 每次运行都会变，必须一起提交，否则工作区常年是脏的，
# 下次 git pull --rebase 会直接罢工
git add index.html scripts/news_cache.json scripts/news_update_log.txt
if ! git diff --cached --quiet; then
    git commit -q -m "News refresh $(date '+%Y-%m-%d')"
    if git push origin main --quiet 2>/dev/null; then
        echo "  ✓ 已推送至 GitHub"
    else
        echo "  ✗ 推送失败（本地已提交，联网后可重跑本脚本补推）"
    fi
else
    echo "  无新内容，跳过提交"
fi

# ── 日报草稿 ───────────────────────────────────────────────
if [ "$DO_MAIL" -eq 1 ]; then
    echo
    echo "▸ 生成日报邮件草稿…"
    python3 scripts/send_daily_digest.py $DIGEST_DATE
fi

echo
echo "════════════════════════════════════════"
echo "完成。邮件在 Mail 的草稿箱里，确认后手动发送。"
echo "════════════════════════════════════════"
