"""帧的来源 —— 渲染层和素材在这里解耦。

窗口只会问 provider 要"当前这一帧的 QImage"，不关心这帧是从 PNG 读出来的
还是当场用 QPainter 画的。两个实现:

  FolderSprites  读 sprites/{state}/*.png，有素材时自动启用
  BlobPet        默认角色，全部用 QPainter 现画

角色是照着一只黄色团子的造型**重画**的，不是把参考图打包进来:
仓库是公开的，塞别人的图进来在素材版权上说不清楚。而且画出来的角色能跟着
姿态系统一起形变、按状态换表情和手势，一张位图做不到这些。

另外注意返回的是 QImage 而不是直接往窗口上画 —— 因为窗口做"点击穿透"时
需要按像素读 alpha，正好复用这张图，不用多渲染一遍。

`Pose` / `pose_for()` 是**从具体画法里抽出来的**: 每个状态该怎么挤压、拉伸、
偏移、旋转，和"这只宠物长什么样"无关。所以将来换角色时，可以直接套同一套姿态。
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
    QRadialGradient,
)

from .state import State

PET_SIZE = 144          # 逻辑像素，窗口就是这么大的正方形
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
        return Pose(sx=1 - 0.025 * breathe, sy=1 + 0.03 * breathe)
    if state is State.WALK:
        step = math.sin(t * 9.0)
        return Pose(sx=1 + 0.025 * step, sy=1 - 0.025 * step, dy=-abs(step) * 3.0)
    if state is State.DRAG:
        return Pose(sx=0.90, sy=1.14, dy=-2.0)
    if state is State.FALL:
        return Pose(sx=0.93, sy=1.10)
    if state is State.SLEEP:
        return Pose(sx=1.10, sy=0.84)
    if state is State.HAPPY:
        hop = math.sin(t * 8.0)
        return Pose(sx=1 - 0.035 * hop, sy=1 + 0.045 * hop, dy=-abs(hop) * 6.0)
    if state is State.CLING:
        # 贴着墙被压扁一点，并朝墙的方向蹭过去；轻微摇晃表示挂不太稳
        return Pose(sx=0.94, sy=1.06, dx=-facing * 4.0, rot=math.sin(t * 2.2) * 2.5)
    if state is State.DIZZY:
        return Pose(sx=1.04, sy=0.97, rot=math.sin(t * 8.0) * 7.0)
    return Pose()


class BlobPet:
    """一只黄色团子: 无颈的梨形身体、奶油色肚子、大圆眼、深橄榄色的手。

    刻意画成抗锯齿的软边 + 半透明投影 —— 这正是选 PySide6 而不是 tkinter
    的理由: tkinter 的色键透明做不出这种边缘，只能硬抠一个颜色。
    """

    size = PET_SIZE

    BODY_TOP = QColor(255, 227, 130)
    BODY_MID = QColor(251, 206, 76)
    BODY_LOW = QColor(238, 178, 44)
    OUTLINE = QColor(186, 128, 24, 70)
    BELLY = QColor(253, 248, 231)
    BELLY_EDGE = QColor(250, 232, 180)
    HAND = QColor(112, 114, 86)
    IRIS = QColor(170, 214, 190)
    PUPIL = QColor(24, 26, 24)
    MOUTH = QColor(146, 104, 46)
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

        # 0.66 不是随便定的: 举手 / 甩手 / 旋转叠加起来最宽的是 dizzy 和 fall，
        # 留这点余量它们才不会顶到画布边被裁(tests 有余量断言盯着)。
        w = self.size * 0.66 * pose.sx
        h = self.size * 0.76 * pose.sy
        cx = self.size / 2 + pose.dx
        bottom = self.size * 0.95 + pose.dy

        # 影子不跟着旋转，否则贴墙晃动时地面会跟着歪
        if state is not State.CLING:
            self._paint_shadow(p, w, bottom, pose.sy)

        p.save()
        p.translate(cx, bottom)
        p.rotate(pose.rot)
        p.translate(-cx, -bottom)

        grad = QLinearGradient(0, bottom - h, 0, bottom)
        grad.setColorAt(0.0, self.BODY_TOP)
        grad.setColorAt(0.55, self.BODY_MID)
        grad.setColorAt(1.0, self.BODY_LOW)
        p.setBrush(QBrush(grad))
        p.setPen(QPen(self.OUTLINE, 1.2))
        p.drawPath(self._body_path(cx, bottom, w, h))

        self._paint_belly(p, cx, bottom, w, h)
        self._paint_arms(p, state, t, facing, cx, bottom, w, h)
        self._paint_face(p, state, t, facing, cx, bottom, w, h)
        p.restore()

        # 特效画在旋转之外，让它们始终朝上飘
        if state is State.SLEEP:
            self._paint_zzz(p, cx + w * 0.34, bottom - h * 0.98, t)
        elif state is State.HAPPY:
            self._paint_hearts(p, cx, bottom - h, t)
        elif state is State.DIZZY:
            self._paint_stars(p, cx, bottom - h * 1.02, t)

    def _body_path(self, cx: float, bottom: float, w: float, h: float) -> QPainterPath:
        """梨形: 圆头 → 溜肩 → 下盘宽。没有脖子，一条曲线从头顶走到底。

        关键在头顶那段的控制点 y 要压到 top: 切线水平，头才是圆的。
        控制点稍微抬一点就会收成蛋尖，整只看起来像颗鸡蛋而不是团子。
        """
        top = bottom - h
        hw = w / 2
        path = QPainterPath()
        path.moveTo(cx - hw * 0.86, bottom)
        # 左下 → 最宽处(约七成八高度)
        path.cubicTo(cx - hw * 1.02, bottom - h * 0.04,
                     cx - hw * 1.03, top + h * 0.88,
                     cx - hw * 1.00, top + h * 0.78)
        # 最宽处 → 脸颊。第二个控制点收到 0.55 制造一个很轻的"腰"，
        # 少了它整只会退化成一个圆锥，看不出头和身体的区别。
        path.cubicTo(cx - hw * 0.95, top + h * 0.55,
                     cx - hw * 0.55, top + h * 0.42,
                     cx - hw * 0.55, top + h * 0.20)
        # 脸颊 → 头顶。末控制点压在 top 上，切线水平，头才是圆的
        path.cubicTo(cx - hw * 0.55, top + h * 0.06,
                     cx - hw * 0.34, top,
                     cx, top)
        # 右半边镜像
        path.cubicTo(cx + hw * 0.34, top,
                     cx + hw * 0.55, top + h * 0.06,
                     cx + hw * 0.55, top + h * 0.20)
        path.cubicTo(cx + hw * 0.55, top + h * 0.42,
                     cx + hw * 0.95, top + h * 0.55,
                     cx + hw * 1.00, top + h * 0.78)
        path.cubicTo(cx + hw * 1.03, top + h * 0.88,
                     cx + hw * 1.02, bottom - h * 0.04,
                     cx + hw * 0.86, bottom)
        # 底部微鼓，坐着的感觉
        path.cubicTo(cx + hw * 0.46, bottom + h * 0.035,
                     cx - hw * 0.46, bottom + h * 0.035,
                     cx - hw * 0.86, bottom)
        path.closeSubpath()
        return path

    def _paint_belly(self, p: QPainter, cx: float, bottom: float, w: float, h: float) -> None:
        """肚子用径向渐变淡出，不描边 —— 参考造型里它是和身体融在一起的。"""
        # 宽扁一点、别全不透明: 满不透明的正圆会读成"贴了个白球"，
        # 参考造型里肚子是和身体融在一起的一片浅色。
        cy = bottom - h * 0.21
        rx, ry = w * 0.35, h * 0.23
        grad = QRadialGradient(QPointF(cx, cy), max(rx, ry))
        grad.setColorAt(0.0, QColor(253, 249, 236, 238))
        grad.setColorAt(0.50, QColor(253, 247, 229, 228))
        grad.setColorAt(0.84, QColor(251, 236, 197, 120))
        grad.setColorAt(1.0, QColor(250, 232, 180, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawEllipse(QPointF(cx, cy), rx, ry)

    def _paint_shadow(self, p: QPainter, w: float, bottom: float, sy: float) -> None:
        # 压得越扁影子越大，看起来才像贴着地面
        sw = w * (1.05 - 0.15 * sy)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 46))
        p.drawEllipse(QRectF(self.size / 2 - sw / 2, bottom - 5, sw, 11))

    # --- 手臂 -------------------------------------------------------------
    def _arm_angles(self, state: State, t: float, facing: int) -> tuple[float, float]:
        """角度: 0 = 垂直向下, 正 = 往外张开, >90 = 举过肩。"""
        if state is State.WALK:
            swing = math.sin(t * 9.0) * 15.0
            return 22.0 - swing, 22.0 + swing
        if state is State.HAPPY:
            return 152.0, 152.0          # 举起来比大拇指
        if state is State.FALL:
            return 145.0, 145.0          # 掉下去时手往上扬
        if state is State.DRAG:
            return 36.0, 36.0
        if state is State.DIZZY:
            return 50.0, 50.0
        if state is State.SLEEP:
            return 14.0, 14.0
        if state is State.CLING:
            # facing=1 表示挂在左墙上，靠墙那侧的手抓着墙
            return (148.0, 28.0) if facing > 0 else (28.0, 148.0)
        breathe = math.sin(t * 2.4) * 2.0
        return 22.0 + breathe, 22.0 + breathe

    def _paint_arms(
        self, p: QPainter, state: State, t: float, facing: int,
        cx: float, bottom: float, w: float, h: float,
    ) -> None:
        left, right = self._arm_angles(state, t, facing)
        # 肩点埋在身体里，手要能探到轮廓外面 —— 不然只剩两个深色小疙瘩贴在边上。
        # 但手臂别太长: 垂到底会读成脚，参考造型里手是在身体中段的。
        shoulder_y = bottom - h * 0.46
        shoulder_x = w * 0.36
        length = h * 0.22
        thickness = w * 0.19
        hand_r = w * 0.115
        thumb = state is State.HAPPY

        self._draw_arm(p, QPointF(cx - shoulder_x, shoulder_y), -1, left, length, thickness, hand_r, thumb)
        self._draw_arm(p, QPointF(cx + shoulder_x, shoulder_y), 1, right, length, thickness, hand_r, thumb)

    def _draw_arm(
        self, p: QPainter, shoulder: QPointF, side: int, angle: float,
        length: float, thickness: float, hand_r: float, thumb: bool,
    ) -> None:
        a = math.radians(angle)
        end = QPointF(
            shoulder.x() + side * math.sin(a) * length,
            shoulder.y() + math.cos(a) * length,
        )
        p.setPen(QPen(self.BODY_MID, thickness, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(shoulder, end)

        p.setPen(Qt.NoPen)
        p.setBrush(self.HAND)
        p.drawEllipse(end, hand_r, hand_r * 0.94)
        if thumb:
            # 竖起的大拇指: 一个从拳头上方探出来的圆角小块
            p.drawRoundedRect(
                QRectF(end.x() - hand_r * 0.26, end.y() - hand_r * 1.95,
                       hand_r * 0.52, hand_r * 1.25),
                hand_r * 0.26, hand_r * 0.26,
            )

    # --- 表情 -------------------------------------------------------------
    def _paint_face(
        self, p: QPainter, state: State, t: float, facing: int,
        cx: float, bottom: float, w: float, h: float,
    ) -> None:
        eye_y = bottom - h * 0.79
        gap = w * 0.155
        shift = facing * w * 0.028          # 眼睛朝行进方向偏一点
        if state is State.CLING:
            shift = -shift                  # 挂墙上时往屏幕内侧瞟
        left = QPointF(cx - gap + shift, eye_y)
        right = QPointF(cx + gap + shift, eye_y)
        r = w * 0.082

        blinking = (t % 3.4) < 0.11
        if state is State.SLEEP or (blinking and state not in (State.HAPPY, State.DIZZY)):
            self._closed_eyes(p, left, right, r)
        elif state is State.HAPPY:
            self._happy_eyes(p, left, right, r)
        elif state is State.DIZZY:
            self._dizzy_eyes(p, left, right, r)
        else:
            wide = 1.25 if state in (State.DRAG, State.FALL) else 1.0
            self._open_eyes(p, left, right, r, wide)

        self._paint_mouth(p, state, cx + shift, eye_y + r * 2.5, w)

    def _open_eyes(self, p: QPainter, left: QPointF, right: QPointF, r: float, wide: float) -> None:
        for c in (left, right):
            p.setPen(Qt.NoPen)
            p.setBrush(self.IRIS)
            p.drawEllipse(c, r, r * wide)
            p.setBrush(self.PUPIL)
            p.drawEllipse(c, r * 0.58, r * 0.58 * wide)
            p.setBrush(QColor(255, 255, 255, 225))
            p.drawEllipse(QPointF(c.x() + r * 0.24, c.y() - r * 0.30), r * 0.19, r * 0.19)

    def _closed_eyes(self, p: QPainter, left: QPointF, right: QPointF, r: float) -> None:
        p.setPen(QPen(self.PUPIL, r * 0.34, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        for c in (left, right):
            p.drawLine(QPointF(c.x() - r * 0.75, c.y()), QPointF(c.x() + r * 0.75, c.y()))

    def _happy_eyes(self, p: QPainter, left: QPointF, right: QPointF, r: float) -> None:
        """开心就是把眼睛画成向上的弧: ^ ^"""
        p.setPen(QPen(self.PUPIL, r * 0.34, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        for c in (left, right):
            path = QPainterPath()
            path.moveTo(c.x() - r * 0.85, c.y() + r * 0.34)
            path.quadTo(c.x(), c.y() - r * 0.72, c.x() + r * 0.85, c.y() + r * 0.34)
            p.drawPath(path)

    def _dizzy_eyes(self, p: QPainter, left: QPointF, right: QPointF, r: float) -> None:
        """摔懵了画成 ✕ ✕，比画螺旋清楚，尺寸小的时候也糊不掉。"""
        p.setPen(QPen(self.PUPIL, r * 0.30, Qt.SolidLine, Qt.RoundCap))
        for c in (left, right):
            p.drawLine(QPointF(c.x() - r * 0.7, c.y() - r * 0.7), QPointF(c.x() + r * 0.7, c.y() + r * 0.7))
            p.drawLine(QPointF(c.x() - r * 0.7, c.y() + r * 0.7), QPointF(c.x() + r * 0.7, c.y() - r * 0.7))

    def _paint_mouth(self, p: QPainter, state: State, cx: float, y: float, w: float) -> None:
        half = w * 0.075
        depth = w * 0.05
        if state is State.HAPPY:
            half, depth = w * 0.095, w * 0.085
        elif state is State.SLEEP:
            half, depth = w * 0.045, w * 0.022
        elif state is State.DIZZY:
            depth = -depth * 0.6            # 往下撇
        p.setPen(QPen(self.MOUTH, max(1.2, w * 0.017), Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        path = QPainterPath()
        path.moveTo(cx - half, y)
        path.quadTo(cx, y + depth, cx + half, y)
        p.drawPath(path)

    # --- 特效 -------------------------------------------------------------
    def _paint_zzz(self, p: QPainter, x: float, y: float, t: float) -> None:
        """三个 Z 轮流向上飘并淡出 —— 顺手验证一下逐像素 alpha 确实生效。"""
        font = QFont()
        font.setBold(True)
        for i in range(3):
            phase = (t * 0.55 + i / 3.0) % 1.0
            alpha = int(220 * math.sin(phase * math.pi))
            if alpha <= 0:
                continue
            font.setPointSizeF(7 + phase * 6)
            p.setFont(font)
            p.setPen(QColor(120, 132, 148, alpha))
            p.drawText(QPointF(x + phase * 9, y - phase * 20), "z")

    def _paint_hearts(self, p: QPainter, cx: float, top: float, t: float) -> None:
        # 起点压在头顶**之下**、升幅也收着: happy 的 pose 本来就把整只往上抬,
        # 再让爱心往上飘 18px 就会飘出画布被裁掉(tests 里有余量断言盯着)。
        p.setPen(Qt.NoPen)
        for i in range(3):
            phase = (t * 0.9 + i / 3.0) % 1.0
            alpha = int(230 * math.sin(phase * math.pi))
            if alpha <= 0:
                continue
            drift = math.sin(phase * 6.0 + i) * 6.0
            colour = QColor(self.HEART)
            colour.setAlpha(alpha)
            p.setBrush(colour)
            p.drawPath(
                _heart_path(cx + drift + (i - 1) * 15, top + 5 - phase * 12, 3.5 + phase * 2.5)
            )

    def _paint_stars(self, p: QPainter, cx: float, top: float, t: float) -> None:
        """三颗星星绕着头顶转圈 —— 椭圆轨道，看起来才有透视。"""
        p.setPen(Qt.NoPen)
        p.setBrush(self.STAR)
        for i in range(3):
            a = t * 5.0 + i * (2 * math.pi / 3)
            p.drawPath(_sparkle_path(cx + math.cos(a) * 19, top - 5 + math.sin(a) * 5, 4.5))


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
    return BlobPet()
