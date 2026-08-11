"""v-pet 入口。

    python main.py
    python main.py --selftest      # 不开窗口，渲一遍所有状态，用退出码报告结果
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from vpet import crashlog, instance
from vpet.config import Config
from vpet.paths import sprites_dir
from vpet.render import pick_provider
from vpet.state import Posture, State
from vpet.window import PetWindow


def selftest() -> int:
    """打包后的验证入口。

    存在的理由：为了压体积，打包时删掉了几十兆用不上的 Qt DLL。
    删错一个的表现是 exe 双击没反应 —— 它是 console=False 的窗口程序，
    连异常都没地方显示。所以留一条能用**退出码**回话的路径。

    "进程还活着"证明不了什么，得真的渲出像素来。
    """
    app = QApplication(sys.argv)
    try:
        provider = pick_provider(sprites_dir())
        for state in State:
            for posture in Posture:
                img = provider.render(state, 0.7, 1, 1.5, posture)
                if img.isNull() or img.width() == 0:
                    return 1
                # 全透明说明画了个空的，和渲染失败一样糟
                if not any(img.pixelColor(x, y).alpha() > 8
                           for y in range(0, img.height(), 7)
                           for x in range(0, img.width(), 7)):
                    return 1
        PetWindow(provider, Config())        # 托盘图标、菜单、Win32 调用都在构造里
    except Exception:
        return 1
    finally:
        app.quit()
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()

    # 先装一次不带通知的：窗口还没建起来就崩的话，至少日志要留下。
    # 这个程序没有控制台，未捕获异常的表现是"双击了没反应"或者"宠物突然不见了"。
    crashlog.install()

    # 单实例：两只宠物写的是同一个 config.json，位置和设置会互相覆盖。
    # 不是静默退出 —— 招呼一声让已经在跑的那只露个面，否则用户看到的是
    # "双击了没反应"，尤其是它正被"藏起来"的时候。
    if not instance.acquire():
        instance.broadcast_wake()
        return 0

    app = QApplication(sys.argv)
    # 托盘还在，"藏起来"就不该导致进程退出
    app.setQuitOnLastWindowClosed(False)

    config = Config.load()
    # 不能写 Path(__file__).parent —— 打包后它不指向 exe 所在目录
    provider = pick_provider(sprites_dir(), config.size)
    window = PetWindow(provider, config)
    # 托盘建好之后再装一次，这回带上通知 —— 让用户知道崩了、日志在哪
    crashlog.install(notify=window.report_crash)

    # 挂在 aboutToQuit 上而不是 closeEvent: 这个窗口正常情况下根本不会被 close，
    # 退出走的是托盘/菜单里的 QApplication.quit()。
    app.aboutToQuit.connect(window.save_config)

    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
