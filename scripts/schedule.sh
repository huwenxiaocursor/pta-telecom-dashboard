#!/bin/bash
# 启停两个 launchd 定时任务（抓新闻 09:30、日报 10:10）。
#
#   ./scripts/schedule.sh status   # 看当前状态
#   ./scripts/schedule.sh off      # 停掉自动任务，改用 run_manual.sh 手动跑（去国内时用）
#   ./scripts/schedule.sh on       # 恢复自动任务（回巴基斯坦时用）
#
# 为什么去国内要关：launchd 按**本机时区**触发，回国后 09:30 CST = 06:30 PKT，
# 巴基斯坦媒体当天还没开始发稿；而且代理没挂好时会空跑一遍，把当天坐实成
# "无新增新闻"。手动模式下由你先挂好 Clash 再跑，时机自己掌握。

set -u
LABELS=("com.cmpak.telecom-news-fetch" "com.cmpak.telecom-digest")
AGENTS="$HOME/Library/LaunchAgents"

usage() { echo "用法：$0 {on|off|status}"; exit 1; }
[ $# -eq 1 ] || usage

case "$1" in
  status)
    echo "定时任务状态："
    for L in "${LABELS[@]}"; do
        if launchctl list | grep -q "$L"; then
            HH=$(plutil -extract StartCalendarInterval.Hour   raw "$AGENTS/$L.plist" 2>/dev/null)
            MM=$(plutil -extract StartCalendarInterval.Minute raw "$AGENTS/$L.plist" 2>/dev/null)
            printf "  %-32s 已启用   每天 %02d:%02d（本机时区 %s）\n" "$L" "${HH:-?}" "${MM:-?}" "$(date +%Z)"
        else
            printf "  %-32s 已停用\n" "$L"
        fi
    done
    echo
    echo "本机时区：$(date '+%Z %z')　当前时间：$(date '+%Y-%m-%d %H:%M')"
    ;;

  off)
    for L in "${LABELS[@]}"; do
        launchctl bootout "gui/$UID/$L" 2>/dev/null \
            || launchctl unload -w "$AGENTS/$L.plist" 2>/dev/null
        echo "  已停用 $L"
    done
    echo
    echo "改用手动模式：先挂好代理，再跑 ./scripts/run_manual.sh"
    ;;

  on)
    for L in "${LABELS[@]}"; do
        launchctl bootstrap "gui/$UID" "$AGENTS/$L.plist" 2>/dev/null \
            || launchctl load -w "$AGENTS/$L.plist" 2>/dev/null
        echo "  已启用 $L"
    done
    echo
    echo "注意：launchd 按本机时区触发。若人在国内而想按巴基斯坦时间跑，"
    echo "需把两个 plist 的 Hour 各 +3（09:30→12:30、10:10→13:10）后重新 on。"
    ;;

  *) usage ;;
esac
