"""帧的来源 —— 渲染层和素材在这里解耦。

窗口只会问 provider 要"当前这一帧的 QImage"，不关心这帧是从 PNG 读出来的
还是当场用 QPainter 画的。两个实现:

  FolderSprites  读 sprites/{state}/*.png，有素材时自动启用
  ProceduralPet  没素材时现画一只占位史莱姆

所以第一版**一帧图都不用画**。等你画好了丢进 sprites/ 就自动换皮，
不用改一行代码。

另外注意返回的是 QImage 而不是直接往窗口上画 —— 因为窗口做"点击穿透"时
需要按像素读 alpha，正好复用这张图，不用多渲染一遍。
"""

from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
)

from .state import State

PET_SIZE = 108          # 逻辑像素，窗口就是这么大的正方形
SPRITE_FPS = 8          # 外部素材的播放帧率


class ProceduralPet:
    """用 QPainter 现画的占位角色。

    刻意画成抗锯齿的软边 + 半透明投影 —— 这正是选 PySide6 而不是 tkinter
    的理由: tkinter 的色键透明做不出这种边缘，只能硬抠一个颜色。
    """

    size = PET_SIZE

    BODY_TOP = QColor(126, 232, 205)
    BODY_BOTTOM = QColor(56, 178, 172)
    OUTLINE = QColor(22, 110, 108, 90)
    EYE = QColor(28, 48, 58)

    def render(self, state: State, t: float, facing: int, dpr: float = 1.0) -> QImage:
        img = QImage(int(self.size * dpr), int(self.size * dpr), QImage.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.transparent)

        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(dpr, dpr)
        try:
            self._paint(p, state, t, facing)
        finally:
            p.end()
        return img

    # --- 具体画法 ---------------------------------------------------------
    def _paint(self, p: QPainter, state: State, t: float, facing: int) -> None:
        sx, sy, lean, bob = self._pose(state, t)

        w = self.size * 0.68 * sx
        h = self.size * 0.60 * sy
        cx = self.size / 2 + lean
        bottom = self.size * 0.90 + bob

        self._paint_shadow(p, w, bottom, sy)

        body = self._blob_path(cx, bottom, w, h)
        grad = QLinearGradient(0, bottom - h, 0, bottom)
        grad.setColorAt(0.0, self.BODY_TOP)
        grad.setColorAt(1.0, self.BODY_BOTTOM)
        p.setBrush(QBrush(grad))
        p.setPen(self.OUTLINE)
        p.drawPath(body)

        # 高光: 一小块低透明度白色，让它看起来是果冻不是色块
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 70))
        p.drawEllipse(QRectF(cx - w * 0.30, bottom - h * 0.82, w * 0.26, h * 0.20))

        self._paint_face(p, state, t, facing, cx, bottom, w, h)

    def _pose(self, state: State, t: float) -> tuple[float, float, float, float]:
        """返回 (横向缩放, 纵向缩放, 左右偏移, 上下偏移)。挤压拉伸是廉价又有效的动画。"""
        if state is State.IDLE:
            breathe = math.sin(t * 2.4)
            return 1 - 0.04 * breathe, 1 + 0.05 * breathe, 0.0, 0.0
        if state is State.WALK:
            step = math.sin(t * 9.0)
            return 1 + 0.03 * step, 1 - 0.03 * step, 0.0, -abs(step) * 3.0
        if state is State.DRAG:
            return 0.86, 1.20, 0.0, -2.0
        if state is State.FALL:
            return 0.90, 1.14, 0.0, 0.0
        if state is State.SLEEP:
            return 1.16, 0.78, 0.0, 0.0
        return 1.0, 1.0, 0.0, 0.0

    def _blob_path(self, cx: float, bottom: float, w: float, h: float) -> QPainterPath:
        """一个底部微鼓的水滴形，比纯椭圆更像活物。"""
        x0, x1, top = cx - w / 2, cx + w / 2, bottom - h
        path = QPainterPath()
        path.moveTo(x0, bottom)
        path.cubicTo(x0 - w * 0.06, top + h * 0.18, x0 + w * 0.16, top, cx, top)
        path.cubicTo(x1 - w * 0.16, top, x1 + w * 0.06, top + h * 0.18, x1, bottom)
        path.cubicTo(x1 - w * 0.14, bottom + h * 0.07, x0 + w * 0.14, bottom + h * 0.07, x0, bottom)
        path.closeSubpath()
        return path

    def _paint_shadow(self, p: QPainter, w: float, bottom: float, sy: float) -> None:
        # 压得越扁影子越大，看起来才像贴着地面
        sw = w * (1.15 - 0.15 * sy)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 46))
        p.drawEllipse(QRectF(self.size / 2 - sw / 2, bottom - 4, sw, 10))

    def _paint_face(
        self, p: QPainter, state: State, t: float, facing: int,
        cx: float, bottom: float, w: float, h: float,
    ) -> None:
        eye_y = bottom - h * 0.52
        gap = w * 0.19
        shift = facing * w * 0.06          # 眼睛朝行进方向偏一点
        left = QPointF(cx - gap + shift, eye_y)
        right = QPointF(cx + gap + shift, eye_y)
        r = w * 0.062

        if state is State.SLEEP:
            p.setPen(Qt.NoPen)
            p.setBrush(self.EYE)
            for c in (left, right):        # 闭眼画成两条短横
                p.drawRoundedRect(QRectF(c.x() - r, c.y() - r * 0.28, r * 2, r * 0.56), r * 0.28, r * 0.28)
            self._paint_zzz(p, cx + w * 0.42, bottom - h * 1.05, t)
            return

        # 每 3.4 秒眨一次，眨眼是"活着"最便宜的信号
        if (t % 3.4) < 0.11:
            p.setPen(Qt.NoPen)
            p.setBrush(self.EYE)
            for c in (left, right):
                p.drawRoundedRect(QRectF(c.x() - r, c.y() - r * 0.24, r * 2, r * 0.48), r * 0.24, r * 0.24)
            return

        stretch = 1.5 if state in (State.DRAG, State.FALL) else 1.0   # 被抓住时瞪大眼
        p.setPen(Qt.NoPen)
        p.setBrush(self.EYE)
        for c in (left, right):
            p.drawEllipse(c, r, r * 1.25 * stretch)
        p.setBrush(QColor(255, 255, 255, 210))
        for c in (left, right):
            p.drawEllipse(QPointF(c.x() + r * 0.32, c.y() - r * 0.42), r * 0.30, r * 0.30)

    def _paint_zzz(self, p: QPainter, x: float, y: float, t: float) -> None:
        """三个 Z 轮流向上飘并淡出 —— 顺手验证一下逐像素 alpha 确实生效。"""
        font = QFont()
        font.setBold(True)
        for i in range(3):
            phase = (t * 0.55 + i / 3.0) % 1.0
            alpha = int(210 * math.sin(phase * math.pi))
            if alpha <= 0:
                continue
            font.setPointSizeF(7 + phase * 6)
            p.setFont(font)
            p.setPen(QColor(255, 255, 255, alpha))
            p.drawText(QPointF(x + phase * 9, y - phase * 22), "z")


class FolderSprites:
    """按 sprites/{state}/*.png 的约定加载素材。文件名排序即帧序。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.frames: dict[str, list[QImage]] = {}
        for state in State:
            folder = root / state.value
            if not folder.is_dir():
                continue
            loaded = []
            for png in sorted(folder.glob("*.png")):
                img = QImage(str(png))
                if not img.isNull():
                    loaded.append(img.convertToFormat(QImage.Format_ARGB32_Premultiplied))
            if loaded:
                self.frames[state.value] = loaded
        first = next(iter(self.frames.values()), None)
        self.size = first[0].width() if first else PET_SIZE

    def has_frames(self) -> bool:
        return bool(self.frames)

    def render(self, state: State, t: float, facing: int, dpr: float = 1.0) -> QImage:
        # 缺哪个状态就退回 idle，素材可以一个状态一个状态地补
        seq = self.frames.get(state.value) or self.frames.get(State.IDLE.value)
        if not seq:
            return QImage()
        img = seq[int(t * SPRITE_FPS) % len(seq)]
        if facing < 0:
            img = img.mirrored(True, False)
        return img


def pick_provider(sprites_dir: Path):
    """有素材就用素材，没有就用现画的。"""
    if sprites_dir.is_dir():
        folder = FolderSprites(sprites_dir)
        if folder.has_frames():
            return folder
    return ProceduralPet()
