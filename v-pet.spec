# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置。用 `python tools/build.py` 跑，别直接调 pyinstaller ——
构建脚本还要先生成图标、事后把 sprites/ 放到 exe 旁边。

**用 onedir 而不是 onefile。** onefile 每次启动都要把整个包体解压到临时目录，
PySide6 有一百多兆，冷启动要好几秒。一个开机自启的桌宠不能这样 ——
装在 D 盘一个文件夹里、快捷方式指过去，效果一样是"免安装"。

excludes 是体积的大头。PySide6 默认会把 QtWebEngine、QtQuick、Qt3D 这些
一个字节都用不上的东西拖进来，不排掉包体能翻好几倍。
"""

from pathlib import Path  # noqa: F401  (UNWANTED_DLLS 过滤要用)

ROOT = Path(SPECPATH)  # noqa: F821  (PyInstaller 注入)

# 用不上的 Qt 模块。只留 QtCore / QtGui / QtWidgets。
QT_EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtSpatialAudio",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtLocation",
    "PySide6.QtSerialPort", "PySide6.QtSerialBus", "PySide6.QtWebSockets",
    "PySide6.QtWebChannel", "PySide6.QtWebView", "PySide6.QtHttpServer",
    "PySide6.QtNetworkAuth", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtStateMachine", "PySide6.QtSensors", "PySide6.QtTextToSpeech",
    "PySide6.QtDesigner", "PySide6.QtUiTools", "PySide6.QtHelp",
    "PySide6.QtPrintSupport", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
]

# 标准库里这个程序碰都不碰的部分
STDLIB_EXCLUDES = [
    "tkinter", "test", "distutils", "setuptools", "pip",
    "lib2to3", "pydoc_data", "xmlrpc", "pdb", "doctest",
]

# excludes 只作用于 **Python 模块分析**，而 PySide6 的 hook 是整包拷 DLL 的 ——
# 排掉 PySide6.QtQml 并不会让 Qt6Qml.dll 不进包。所以还得按文件名再筛一道。
# 这里删掉的加起来约 45MB，其中 opengl32sw.dll 一个就占 20MB(Mesa 的软件 OpenGL
# 回退，纯光栅绘制的 Widgets 程序碰都不碰它)。
# 删错的代价是 exe 双击没反应，所以 build.py 会用 `--selftest` 真渲一遍验证。
UNWANTED_DLLS = {
    "opengl32sw.dll",           # 软件 OpenGL 回退，20MB
    "d3dcompiler_47.dll",       # ANGLE 的 D3D 着色器编译器，同理用不上
    "qt6quick.dll", "qt6qml.dll", "qt6qmlmodels.dll", "qt6qmlmeta.dll",
    "qt6qmlworkerscript.dll", "qt6quickcontrols2.dll", "qt6quicktemplates2.dll",
    "qt6pdf.dll", "qt6pdfquick.dll", "qt6pdfwidgets.dll",
    "qt6network.dll", "libcrypto-3.dll", "libssl-3.dll",
    "qt6opengl.dll", "qt6openglwidgets.dll",
    "qt6virtualkeyboard.dll",
}

a = Analysis(  # noqa: F821
    ["main.py"],
    pathex=[str(ROOT)],
    binaries=[],
    # sprites/ 刻意**不打进包体**: 那是留给用户丢自己素材的目录，
    # 打进去就改不了了。构建脚本会把它放到 exe 旁边。
    datas=[],
    hiddenimports=[],
    excludes=QT_EXCLUDES + STDLIB_EXCLUDES,
    noarchive=False,
    optimize=0,
)

a.binaries = [b for b in a.binaries if Path(b[0]).name.lower() not in UNWANTED_DLLS]

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="v-pet",
    debug=False,
    strip=False,
    upx=False,
    console=False,          # 没有控制台窗口，否则开机自启会弹一个黑框
    icon=str(ROOT / "docs" / "v-pet.ico"),
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="v-pet",
)
