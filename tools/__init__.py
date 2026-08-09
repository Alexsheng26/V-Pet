"""构建与文档生成用的脚本。不参与运行时。"""

from __future__ import annotations

import sys


def use_utf8_stdio() -> None:
    """把 stdout / stderr 切成 UTF-8。所有会打印中文的脚本都要先调一次。

    Windows 上 Python 的 stdout 用的是**本地代码页**（GitHub runner 上是 cp1252），
    而且错误处理是 `strict` —— 于是一句带中文的 print 会直接抛 UnicodeEncodeError
    把脚本打挂。stderr 默认是 `backslashreplace` 所以不会挂。

    这个不对称正是 CI 上"跑测试"的 job 能打出中文（unittest 写 stderr）、
    而"打包"的 job 一 print 就死（脚本写 stdout）的原因，也是它一度很难定位的原因。

    本机控制台是 UTF-8（chcp 65001），所以在本地完全看不出来。复现方法：

        PYTHONIOENCODING=cp1252 python tools/make_icon.py out.ico
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass        # 被重定向成了非 TextIOWrapper 的对象，忽略即可
