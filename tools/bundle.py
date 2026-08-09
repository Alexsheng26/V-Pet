"""打包时要从包体里剔掉的 DLL。

单独成一个模块是因为它有**两个使用者**，而且必须用同一份规则：
`v-pet.spec` 用它过滤 `a.binaries`，`tools/build.py` 用它在打包后复查有没有漏网。
两边各写一份的话，规则一改就会不同步，而不同步的表现是"体积悄悄涨回去"。

为什么不能只写精确文件名：v1.0 的发布包里混进了 6.8MB 的
`libcrypto-3-x64.dll`。过滤表里写的是 `libcrypto-3.dll` —— 本地 Python 3.14
打进来的正好叫这个名字，而 CI 的 Python 3.13 打进来的带 `-x64` 后缀，
精确匹配没命中、静默漏过。同一份代码在两台机器上产出不同的文件名，
所以带版本号的那几个必须按前缀匹配。
"""

from __future__ import annotations

# 完整文件名就能锁定的
UNWANTED_EXACT = {
    "opengl32sw.dll",           # Mesa 的软件 OpenGL 回退，单个就 20MB
    "d3dcompiler_47.dll",       # ANGLE 的 D3D 着色器编译器
    "qt6virtualkeyboard.dll",
}

# 文件名里带版本号/架构后缀的，只能按前缀匹配。
# 注意大小写：比较前统一转小写。
UNWANTED_PREFIXES = (
    "libcrypto-",               # OpenSSL，只有 Qt Network 的 TLS 用得上
    "libssl-",
    "qt6quick",                 # 连带 QuickControls2 / QuickTemplates2
    "qt6qml",                   # 连带 QmlModels / QmlMeta / QmlWorkerScript
    "qt6pdf",
    "qt6network",               # 连带 NetworkAuth
    "qt6opengl",                # 连带 OpenGLWidgets
)


def is_unwanted(filename: str) -> bool:
    name = filename.lower()
    return name in UNWANTED_EXACT or name.startswith(UNWANTED_PREFIXES)
