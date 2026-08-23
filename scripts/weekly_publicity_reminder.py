#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每周四 15:00 生成一封"宣传信息填报提醒"邮件草稿（Apple Mail）。

与本仓库其他邮件脚本一致：**只 save 到草稿箱，绝不 send**——由人在草稿箱里
过目后手动发送。这是用户对所有对外邮件的既定要求。

手动运行：python3 scripts/weekly_publicity_reminder.py
自动触发：launchd com.cmpak.weekly-publicity → scripts/run_weekly_publicity.sh
"""
import datetime
import subprocess
import sys

TO_EMAILS = [
    "ramis.ali@zong.com.pk",
    "saira.maroof@zong.com.pk",
]
CC_EMAILS = [
    "saira.mirza@zong.com.pk",
]

SUBJECT = "Weekly publicity information reminder"

SHEET_URL = ("https://docs.google.com/spreadsheets/d/"
             "1Su3XrGsi2G5M6PqcJlvCNrFQ2rEgCK1AoWFw2TI3_Ss/edit?gid=0#gid=0")

BODY = (
    "Hi ramis&saira\n\n"
    "Please fill the online sheet with the publicity information of this week, "
    "thank you for your time.\n\n"
    f"{SHEET_URL}\n"
)


def esc(s: str) -> str:
    """AppleScript 字符串转义。反斜杠必须最先替换，否则会把后面替换出来的
    转义符再转一次。"""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def save_draft() -> None:
    lines = [
        'tell application "Mail"',
        f'set msg to make new outgoing message with properties '
        f'{{subject:"{esc(SUBJECT)}", content:"{esc(BODY)}", visible:true}}',
        "tell msg",
    ]
    for addr in TO_EMAILS:
        lines.append(
            f'make new to recipient with properties {{address:"{esc(addr)}"}}')
    for addr in CC_EMAILS:
        lines.append(
            f'make new cc recipient with properties {{address:"{esc(addr)}"}}')
    lines += [
        "end tell",
        "save msg",          # 只存草稿，不发送
        "end tell",
    ]

    args = ["osascript"]
    for line in lines:
        args += ["-e", line]

    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  AppleScript 错误：{result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    now = datetime.datetime.now()
    print(f"[publicity] {now:%Y-%m-%d %H:%M:%S}（周{'一二三四五六日'[now.weekday()]}）")
    save_draft()
    print(f"  主题：{SUBJECT}")
    print(f"  收件人：{', '.join(TO_EMAILS)}")
    print(f"  抄送：{', '.join(CC_EMAILS)}")
    print("  草稿已保存到 Mail 的草稿箱，待手动确认发送")


if __name__ == "__main__":
    main()
