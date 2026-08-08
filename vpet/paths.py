"""程序自己在哪儿。

这个文件存在的唯一理由是**打包后 `__file__` 不再指向仓库**：

- PyInstaller onedir：`__file__` 指向 exe 旁边的 `_internal/`
- PyInstaller onefile：指向一个每次启动都会重建的临时解包目录，
  往里面写东西下次启动就没了

所以凡是要定位"程序目录"的地方都必须走这里，不能再写
`Path(__file__).parent.parent`。

`sprites/` 特意解析到 **exe 旁边**而不是打包进包体里：那是留给用户丢自己
素材的目录，塞进包体就没法改了。
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def app_dir() -> Path:
    """打包后 = exe 所在目录；开发时 = 仓库根目录。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def sprites_dir() -> Path:
    return app_dir() / "sprites"
