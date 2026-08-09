"""打包成免安装的 Windows 程序。

    pip install pyinstaller
    python tools/build.py

产物在 dist/v-pet/，整个文件夹拷走就能跑，不需要装 Python。

这个脚本干三件 spec 干不了的事：
  1. 先生成图标（图标是从角色本身渲染出来的，不是外部素材）
  2. 打完包把 sprites/ 放到 **exe 旁边**而不是包体里 ——
     PyInstaller 的 datas 只会落进 _internal/，而 paths.app_dir() 指的是 exe 所在目录
  3. 报体积和冷启动时间，这两个数值决定了 onedir/onefile 的取舍
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import use_utf8_stdio  # noqa: E402

use_utf8_stdio()

DIST = ROOT / "dist" / "v-pet"
ICON = ROOT / "docs" / "v-pet.ico"


def run(*args: str) -> None:
    print(f"$ {' '.join(args)}")
    subprocess.run(args, cwd=ROOT, check=True)


def folder_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def main() -> int:
    run(sys.executable, "tools/make_icon.py", str(ICON))
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "v-pet.spec")

    # sprites/ 要在 exe 旁边，用户才找得到、改得了
    sprites = DIST / "sprites"
    sprites.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "sprites" / "README.md", sprites / "README.md")

    exe = DIST / "v-pet.exe"

    # 平台插件必须显式查。为压体积按文件名删过几十兆 DLL，万一把 qwindows.dll
    # 一起删了，程序在本机可能还能跑（Qt 会去别处找），但换台机器就白窗。
    # 以前这件事是靠"真开一个窗口看它活不活得过 6 秒"间接证明的 ——
    # 那需要可交互桌面会话，在 CI 上根本不成立。查文件既确定又跟环境无关。
    plugins = DIST / "_internal" / "PySide6" / "plugins" / "platforms"
    shipped = sorted(p.name for p in plugins.glob("*.dll")) if plugins.is_dir() else []
    print(f"平台插件 {', '.join(shipped) or '一个都没有'}")
    for required in ("qwindows.dll", "qoffscreen.dll"):
        if required not in shipped:
            print(f"  ✗ 缺 {required} —— spec 里的 DLL 过滤删过头了")
            return 1

    print()
    print(f"产物     {DIST}")
    print(f"exe      {exe.stat().st_size / 1024 / 1024:.1f} MB")
    print(f"整个目录 {folder_size(DIST) / 1024 / 1024:.1f} MB"
          f"（{sum(1 for _ in DIST.rglob('*') if _.is_file())} 个文件）")

    # 自检：真渲一遍所有状态。为压体积删了几十兆 Qt DLL，删错一个的表现是
    # 双击没反应 —— console=False 的窗口程序连异常都没地方显示，只能靠退出码。
    started = time.perf_counter()
    check = subprocess.run([str(exe), "--selftest"], cwd=DIST)
    print(f"自检     退出码 {check.returncode} "
          f"{'✓ 所有状态都渲出了像素' if check.returncode == 0 else '✗ 删过头了，把 DLL 加回来'}")
    print(f"自检耗时 {time.perf_counter() - started:.1f}s")
    if check.returncode != 0:
        return 1

    # CI 上跳过这一段：真开一个置顶窗口需要可交互的桌面会话，是整条流水线里
    # 最容易因环境而不是因代码挂掉的一步。而它验的东西 --selftest 已经覆盖了
    # （构造 PetWindow、建托盘、调 Win32），留在本地当最后一道人眼确认。
    if "--no-window-check" in sys.argv:
        print("冷启动   已跳过（--no-window-check）")
        return 0

    started = time.perf_counter()
    proc = subprocess.Popen([str(exe)], cwd=DIST)
    time.sleep(6)
    alive = proc.poll() is None
    proc.terminate()
    print(f"冷启动   {time.perf_counter() - started:.1f}s 内"
          f"{'仍在运行 ✓' if alive else '就退出了 ✗'}")
    return 0 if alive else 1


if __name__ == "__main__":
    raise SystemExit(main())
