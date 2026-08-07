"""v-pet 入口。

    python main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from vpet.render import pick_provider
from vpet.window import PetWindow


def main() -> int:
    app = QApplication(sys.argv)
    # 托盘还在，"藏起来"就不该导致进程退出
    app.setQuitOnLastWindowClosed(False)

    provider = pick_provider(Path(__file__).parent / "sprites")
    window = PetWindow(provider)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
