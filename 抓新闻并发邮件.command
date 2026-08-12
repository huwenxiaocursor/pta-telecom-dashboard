#!/bin/bash
# 双击运行：抓新闻 → 生成日报邮件草稿。
# 人在国内需要代理时，先打开 Clash，再双击本文件。
cd "$(dirname "$0")" || exit 1
./scripts/run_manual.sh
echo
echo "按任意键关闭窗口…"
read -n 1 -s
