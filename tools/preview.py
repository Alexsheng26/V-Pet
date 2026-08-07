"""把每个状态各渲几帧拼成一张对照图，用来肉眼检查角色和动画。

    python tools/preview.py docs/states.png

棋盘格背景是为了让"哪里是真透明"一眼可见 —— 这类项目最容易出的问题就是
以为画好了，结果贴到桌面上边缘一圈白底。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 这里**不能**用 offscreen 平台: 它不加载系统字体，标注和宠物头上的 z
# 全会渲染成豆腐块。反正这是本机看图用的工具，用正常平台即可。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRectF, Qt                      # noqa: E402
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter  # noqa: E402

from vpet.render import BlobPet                             # noqa: E402
from vpet.state import Posture, State                       # noqa: E402

R, C = Posture.RELAXED, Posture.CROSSED

# (标注, 状态, 姿势)。抱手不是一个 State，是待机时的姿势变化，所以单独列一格。
CELLS = [
    ("idle  发呆 / 呼吸", State.IDLE, R),
    ("idle  抱手待机", State.IDLE, C),
    ("walk  溜达 / 追鼠标", State.WALK, R),
    ("drag  被拎起来", State.DRAG, R),
    ("fall  下落", State.FALL, R),
    ("sleep  30 秒没人理", State.SLEEP, R),
    ("happy  摸头 / 双击", State.HAPPY, R),
    ("cling  贴边挂住", State.CLING, R),
    ("dizzy  摔懵了", State.DIZZY, R),
]
FRAMES = (0.35, 0.90, 1.45)     # 取三个时间点，看得出在动
COLS = 3
DPR = 2


def build(pet: BlobPet) -> QImage:
    s = pet.size
    cell_w, cell_h = s * len(FRAMES), s + 28
    rows = (len(CELLS) + COLS - 1) // COLS
    w, h = COLS * cell_w, rows * cell_h

    sheet = QImage(w * DPR, h * DPR, QImage.Format_ARGB32_Premultiplied)
    sheet.setDevicePixelRatio(DPR)       # 设过之后 QPainter 会自己缩放，别再手动 scale
    sheet.fill(QColor(38, 42, 48))

    p = QPainter(sheet)
    p.setRenderHint(QPainter.Antialiasing)

    p.setPen(Qt.NoPen)
    p.setBrush(QColor(50, 55, 62))
    for gy in range(0, h, 12):
        for gx in range(0, w, 12):
            if (gx // 12 + gy // 12) % 2:
                p.drawRect(gx, gy, 12, 12)

    font = QFont("Microsoft YaHei UI", 9)
    p.setFont(font)

    for i, (label, state, posture) in enumerate(CELLS):
        cx, cy = (i % COLS) * cell_w, (i // COLS) * cell_h
        p.setPen(QColor(120, 130, 142))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(cx + 1, cy + 1, cell_w - 2, cell_h - 2))
        for j, t in enumerate(FRAMES):
            p.drawImage(cx + j * s, cy + 22, pet.render(state, t, 1, DPR, posture))
        p.setPen(QColor(226, 232, 240))
        p.drawText(QRectF(cx + 8, cy + 3, cell_w - 16, 19),
                   Qt.AlignLeft | Qt.AlignVCenter, label)
    p.end()
    return sheet


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/states.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    QGuiApplication.instance() or QGuiApplication([])
    sheet = build(BlobPet())
    sheet.save(str(out))
    print(f"{out}  {sheet.width() // DPR}x{sheet.height() // DPR} @{DPR}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
