"""v-pet 入口。

    python main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from vpet.config import Config
from vpet.render import pick_provider
from vpet.window import PetWindow


def main() -> int:
    app = QApplication(sys.argv)
    # 托盘还在，"藏起来"就不该导致进程退出
    app.setQuitOnLastWindowClosed(False)

    config = Config.load()
    provider = pick_provider(Path(__file__).parent / "sprites", config.size)
    window = PetWindow(provider, config)

    # 挂在 aboutToQuit 上而不是 closeEvent: 这个窗口正常情况下根本不会被 close，
    # 退出走的是托盘/菜单里的 QApplication.quit()。
    app.aboutToQuit.connect(window.save_config)

    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
