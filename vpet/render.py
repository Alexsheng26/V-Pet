"""帧的来源 —— 渲染层和素材在这里解耦。

窗口只会问 provider 要"当前这一帧的 QImage"，不关心这帧是从 PNG 读出来的
还是当场用 QPainter 画的。两个实现:

  FolderSprites  读 sprites/{state}/*.png，有素材时自动启用
  ProceduralPet  没素材时现画一只占位史莱姆

所以第一版**一帧图都不用画**。等你画好了丢进 sprites/ 就自动换皮，
不用改一行代码。

另外注意返回的是 QImage 而不是直接往窗口上画 —— 因为窗口做"点击穿透"时
需要按像素读 alpha，正好复用这张图，不用多渲染一遍。

`Pose` / `pose_for()` 是**从具体画法里抽出来的**: 每个状态该怎么挤压、拉伸、
偏移、旋转，和"这只宠物长什么样"无关。所以将来接一张静态图进来当角色时，
可以直接套同一套姿态，不用为它重写一遍动画。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
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
    QPen,
)

from .state import State

PET_SIZE = 108          # 逻辑像素，窗口就是这么大的正方形
SPRITE_FPS = 8          # 外部素材的播放帧率


# --- 姿态 -----------------------------------------------------------------
@dataclass(frozen=True)
class Pose:
    """一帧的形变。挤压拉伸是最廉价也最有效的动画手段。"""

    sx: float = 1.0     # 横向缩放
    sy: float = 1.0     # 纵向缩放
    dx: float = 0.0     # 左右偏移(px)
    dy: float = 0.0     # 上下偏移(px)
    rot: float = 0.0    # 绕底部中心旋转(度)


def pose_for(state: State, t: float, facing: int = 1) -> Pose:
    if state is State.IDLE:
        breathe = math.sin(t * 2.4)
        return Pose(sx=1 - 0.04 * breathe, sy=1 + 0.05 * breathe)
    if state is State.WALK:
        step = math.sin(t * 9.0)
        return Pose(sx=1 + 0.03 * step, sy=1 - 0.03 * step, dy=-abs(step) * 3.0)
    if state is State.DRAG:
        return Pose(sx=0.86, sy=1.20, dy=-2.0)
    if state is State.FALL:
        return Pose(sx=0.90, sy=1.14)
    if state is State.SLEEP:
        return Pose(sx=1.16, sy=0.78)
    if state is State.HAPPY:
        hop = math.sin(t * 8.0)
        return Pose(sx=1 - 0.05 * hop, sy=1 + 0.06 * hop, dy=-abs(hop) * 6.0)
    if state is State.CLING:
        # 贴着墙被压扁一点，并朝墙的方向蹭过去；轻微摇晃表示挂不太稳
        return Pose(sx=0.92, sy=1.08, dx=-facing * 4.0, rot=math.sin(t * 2.2) * 2.5)
    if state is State.DIZZY:
        return Pose(sx=1.05, sy=0.96, rot=math.sin(t * 8.0) * 7.0)
    return Pose()


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
    HEART = QColor(255, 118, 148)
    STAR = QColor(255, 214, 102)

    def render(self, state: State, t: float, facing: int, dpr: float = 1.0) -> QImage:
        img = QImage(int(self.size * dpr), int(self.size * dpr), QImage.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.transparent)

        # 不要在这里再 p.scale(dpr, dpr)。QPainter 作用在设过 devicePixelRatio
        # 的 QImage 上时会自己应用缩放，手动再乘一次等于画大一倍 ——
        # 在 100% 缩放的屏幕上看不出来(dpr=1)，一到 150% 就开始被裁边。
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        try:
            self._paint(p, state, t, facing)
        finally:
            p.end()
        return img

    # --- 具体画法 ---------------------------------------------------------
    def _paint(self, p: QPainter, state: State, t: float, facing: int) -> None:
        pose = pose_for(state, t, facing)

        w = self.size * 0.68 * pose.sx
        h = self.size * 0.60 * pose.sy
        cx = self.size / 2 + pose.dx
        bottom = self.size * 0.90 + pose.dy

        # 影子不跟着旋转，否则贴墙晃动时地面会跟着歪
        if state is not State.CLING:
            self._paint_shadow(p, w, bottom, pose.sy)

        p.save()
        p.translate(cx, bottom)
        p.rotate(pose.rot)
        p.translate(-cx, -bottom)

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
        p.restore()

        # 特效画在旋转之外，让它们始终朝上飘
        if state is State.SLEEP:
            self._paint_zzz(p, cx + w * 0.42, bottom - h * 1.05, t)
        elif state is State.HAPPY:
            self._paint_hearts(p, cx, bottom - h, t)
        elif state is State.DIZZY:
            self._paint_stars(p, cx, bottom - h * 1.05, t)

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

    # --- 表情 -------------------------------------------------------------
    def _paint_face(
        self, p: QPainter, state: State, t: float, facing: int,
        cx: float, bottom: float, w: float, h: float,
    ) -> None:
        eye_y = bottom - h * 0.52
        gap = w * 0.19
        shift = facing * w * 0.06          # 眼睛朝行进方向偏一点
        if state is State.CLING:
            shift = -shift                 # 挂墙上时往下方屏幕内侧瞟
        left = QPointF(cx - gap + shift, eye_y)
        right = QPointF(cx + gap + shift, eye_y)
        r = w * 0.062

        if state is State.SLEEP:
            self._closed_eyes(p, left, right, r)
            return
        if state is State.HAPPY:
            self._happy_eyes(p, left, right, r)
            return
        if state is State.DIZZY:
            self._dizzy_eyes(p, left, right, r)
            return

        # 每 3.4 秒眨一次，眨眼是"活着"最便宜的信号
        if (t % 3.4) < 0.11:
            self._closed_eyes(p, left, right, r)
            return

        stretch = 1.5 if state in (State.DRAG, State.FALL) else 1.0   # 被抓住时瞪大眼
        p.setPen(Qt.NoPen)
        p.setBrush(self.EYE)
        for c in (left, right):
            p.drawEllipse(c, r, r * 1.25 * stretch)
        p.setBrush(QColor(255, 255, 255, 210))
        for c in (left, right):
            p.drawEllipse(QPointF(c.x() + r * 0.32, c.y() - r * 0.42), r * 0.30, r * 0.30)

    def _closed_eyes(self, p: QPainter, left: QPointF, right: QPointF, r: float) -> None:
        p.setPen(Qt.NoPen)
        p.setBrush(self.EYE)
        for c in (left, right):
            p.drawRoundedRect(
                QRectF(c.x() - r, c.y() - r * 0.26, r * 2, r * 0.52), r * 0.26, r * 0.26
            )

    def _happy_eyes(self, p: QPainter, left: QPointF, right: QPointF, r: float) -> None:
        """开心就是把眼睛画成向上的弧: ^ ^"""
        pen = QPen(self.EYE, r * 0.62, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        for c in (left, right):
            path = QPainterPath()
            path.moveTo(c.x() - r, c.y() + r * 0.4)
            path.quadTo(c.x(), c.y() - r * 0.75, c.x() + r, c.y() + r * 0.4)
            p.drawPath(path)

    def _dizzy_eyes(self, p: QPainter, left: QPointF, right: QPointF, r: float) -> None:
        """摔懵了画成 ✕ ✕，比画螺旋清楚，尺寸小的时候也糊不掉。"""
        p.setPen(QPen(self.EYE, r * 0.55, Qt.SolidLine, Qt.RoundCap))
        for c in (left, right):
            p.drawLine(QPointF(c.x() - r * 0.8, c.y() - r * 0.8), QPointF(c.x() + r * 0.8, c.y() + r * 0.8))
            p.drawLine(QPointF(c.x() - r * 0.8, c.y() + r * 0.8), QPointF(c.x() + r * 0.8, c.y() - r * 0.8))

    # --- 特效 -------------------------------------------------------------
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

    def _paint_hearts(self, p: QPainter, cx: float, top: float, t: float) -> None:
        p.setPen(Qt.NoPen)
        for i in range(3):
            phase = (t * 0.9 + i / 3.0) % 1.0
            alpha = int(230 * math.sin(phase * math.pi))
            if alpha <= 0:
                continue
            drift = math.sin(phase * 6.0 + i) * 7.0
            colour = QColor(self.HEART)
            colour.setAlpha(alpha)
            p.setBrush(colour)
            p.drawPath(
                _heart_path(cx + drift + (i - 1) * 13, top - 4 - phase * 22, 4 + phase * 3)
            )

    def _paint_stars(self, p: QPainter, cx: float, top: float, t: float) -> None:
        """三颗星星绕着头顶转圈 —— 椭圆轨道，看起来才有透视。"""
        p.setPen(Qt.NoPen)
        p.setBrush(self.STAR)
        for i in range(3):
            a = t * 5.0 + i * (2 * math.pi / 3)
            p.drawPath(_sparkle_path(cx + math.cos(a) * 17, top - 6 + math.sin(a) * 5, 4.5))


def _heart_path(cx: float, cy: float, s: float) -> QPainterPath:
    path = QPainterPath()
    path.moveTo(cx, cy + s * 0.75)
    path.cubicTo(cx - s * 1.3, cy - s * 0.10, cx - s * 0.45, cy - s * 0.95, cx, cy - s * 0.30)
    path.cubicTo(cx + s * 0.45, cy - s * 0.95, cx + s * 1.3, cy - s * 0.10, cx, cy + s * 0.75)
    path.closeSubpath()
    return path


def _sparkle_path(cx: float, cy: float, r: float) -> QPainterPath:
    """四角星: 四条二次曲线，腰收得很细，就是常见的"闪"。"""
    k = r * 0.22
    path = QPainterPath()
    path.moveTo(cx, cy - r)
    path.quadTo(cx + k, cy - k, cx + r, cy)
    path.quadTo(cx + k, cy + k, cx, cy + r)
    path.quadTo(cx - k, cy + k, cx - r, cy)
    path.quadTo(cx - k, cy - k, cx, cy - r)
    path.closeSubpath()
    return path


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
