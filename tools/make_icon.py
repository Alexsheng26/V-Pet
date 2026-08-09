"""从角色本身生成 exe 用的多尺寸图标。

    python tools/make_icon.py docs/v-pet.ico

Qt 能写 .ico，但一次只写一个尺寸。Windows 要的是一个文件里塞多个尺寸
（任务栏、资源管理器、Alt+Tab 各取所需），所以这里手写 ICO 头，
每个尺寸的负载直接放 PNG（Vista 起支持，比 BMP+掩码干净得多）。

小尺寸不是直接按小尺寸画的：矢量图形在 16px 上画出来全是锯齿。
先画大的再平滑缩下去，边缘干净得多。
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import use_utf8_stdio  # noqa: E402

use_utf8_stdio()

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402

from vpet.render import BlobPet  # noqa: E402
from vpet.state import State  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256)
SUPERSAMPLE = 4


def render_at(size: int) -> QImage:
    pet = BlobPet()
    pet.size = max(size * SUPERSAMPLE, 256)
    img = pet.render(State.IDLE, 0.9, 1, 1.0)
    img.setDevicePixelRatio(1.0)          # 否则 scaled() 会按逻辑尺寸算
    return img.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def png_bytes(img: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(data)


def build_ico(frames: list[tuple[int, bytes]]) -> bytes:
    """ICONDIR + N×ICONDIRENTRY + 各尺寸的 PNG 负载。"""
    header = struct.pack("<HHH", 0, 1, len(frames))     # reserved, type=icon, count
    offset = 6 + 16 * len(frames)
    entries = b""
    payload = b""
    for size, data in frames:
        entries += struct.pack(
            "<BBBBHHII",
            size % 256,     # 宽: 256 要写成 0，这也是尺寸上限的由来
            size % 256,     # 高
            0,              # 调色板颜色数，真彩色填 0
            0,              # reserved
            1,              # 色彩平面
            32,             # 位深
            len(data),
            offset,
        )
        offset += len(data)
        payload += data
    return header + entries + payload


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/v-pet.ico")
    out.parent.mkdir(parents=True, exist_ok=True)
    QGuiApplication.instance() or QGuiApplication([])

    frames = [(s, png_bytes(render_at(s))) for s in SIZES]
    out.write_bytes(build_ico(frames))
    print(f"{out}  {len(SIZES)} 个尺寸 {SIZES}  共 {out.stat().st_size / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
