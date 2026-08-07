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

from .state import Posture, State

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
        # 身体本体变高之后，1.14 的纵向拉伸会把头顶顶出画布，
        # 收到 1.10 —— 拉伸感基本看不出差别，但不会被裁。
        return Pose(sx=0.92, sy=1.10, dy=-1.0)
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
    resizable = True        # 全是矢量画的，改 size 就整体缩放

    BODY_LIGHT = QColor(255, 232, 142)
    BODY_MID = QColor(250, 202, 66)
    BODY_DEEP = QColor(223, 156, 30)
    OUTLINE = QColor(176, 116, 18, 55)
    BELLY = QColor(252, 241, 211)
    BELLY_EDGE = QColor(250, 226, 174)
    HAND = QColor(108, 106, 78)
    HAND_DEEP = QColor(84, 83, 60)
    IRIS = QColor(116, 200, 142)
    PUPIL = QColor(20, 22, 20)
    MOUTH = QColor(150, 106, 44)
    HEART = QColor(255, 118, 148)
    STAR = QColor(255, 214, 102)

    def render(
        self, state: State, t: float, facing: int, dpr: float = 1.0,
        posture: Posture = Posture.RELAXED,
    ) -> QImage:
        # posture 做成带默认值的关键字参数，老的四参数调用不用改。
        # 如果之后还要往这条接口上挂第三个"状态之外的维度"，
        # 就该把它们收进一个 dataclass 了，别继续加位置参数。
        img = QImage(int(self.size * dpr), int(self.size * dpr), QImage.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.transparent)

        # 不要在这里再 p.scale(dpr, dpr)。QPainter 作用在设过 devicePixelRatio
        # 的 QImage 上时会自己应用缩放，手动再乘一次等于画大一倍 ——
        # 在 100% 缩放的屏幕上看不出来(dpr=1)，一到 150% 就开始被裁边。
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        try:
            self._paint(p, state, t, facing, posture)
        finally:
            p.end()
        return img

    # --- 具体画法 ---------------------------------------------------------
    def _paint(self, p: QPainter, state: State, t: float, facing: int, posture: Posture) -> None:
        pose = pose_for(state, t, facing)

        # 宽高比约 0.76: 参考造型是"高而坠"的，不是矮墩墩的。
        # 上限还受举手 / 甩手 / 旋转的叠加约束，太宽 dizzy 会顶到画布边被裁
        # (tests 有余量断言盯着)。
        w = self.size * 0.62 * pose.sx
        h = self.size * 0.82 * pose.sy
        cx = self.size / 2 + pose.dx
        bottom = self.size * 0.95 + pose.dy

        # 影子不跟着旋转，否则贴墙晃动时地面会跟着歪
        if state is not State.CLING:
            self._paint_shadow(p, w, bottom, pose.sy)

        p.save()
        p.translate(cx, bottom)
        p.rotate(pose.rot)
        p.translate(-cx, -bottom)

        # 用径向渐变而不是竖直线性渐变: 参考造型是 3D 渲染的软光，
        # 亮部集中在左上方一小块、四周向暗处滚落，这样才有体积感。
        # 线性渐变只能做出"上浅下深"的贴纸感。
        light = QPointF(cx - w * 0.16, bottom - h * 0.74)
        grad = QRadialGradient(light, h * 1.02)
        grad.setColorAt(0.0, self.BODY_LIGHT)
        grad.setColorAt(0.42, self.BODY_MID)
        grad.setColorAt(1.0, self.BODY_DEEP)
        p.setBrush(QBrush(grad))
        p.setPen(QPen(self.OUTLINE, 1.2))
        p.drawPath(self._body_path(cx, bottom, w, h))

        self._paint_belly(p, cx, bottom, w, h)
        self._paint_arms(p, state, t, facing, cx, bottom, w, h, posture)
        self._paint_face(p, state, t, facing, cx, bottom, w, h)
        p.restore()

        # 特效画在旋转之外，让它们始终朝上飘。
        # 爱心和星星的高度锚在**画布**上而不是身体顶上: 身体顶会随 pose 的
        # 拉伸和抬升上下跑，锚在它上面的话，每次调整比例都要重新算一遍会不会飘出界。
        if state is State.SLEEP:
            self._paint_zzz(p, cx + w * 0.34, bottom - h * 0.98, t)
        elif state is State.HAPPY:
            self._paint_hearts(p, cx, t)
        elif state is State.DIZZY:
            self._paint_stars(p, cx, t)

    def _body_path(self, cx: float, bottom: float, w: float, h: float) -> QPainterPath:
        """梨形: 圆头 → 溜肩 → 下盘宽。没有脖子，一条曲线从头顶走到底。

        关键在头顶那段的控制点 y 要压到 top: 切线水平，头才是圆的。
        控制点稍微抬一点就会收成蛋尖，整只看起来像颗鸡蛋而不是团子。
        """
        top = bottom - h
        hw = w / 2
        path = QPainterPath()
        path.moveTo(cx - hw * 0.90, bottom)
        # 左下 → 最宽处。压到八成高度、几乎贴着底，重心才坠得下去；
        # 参考造型是个葫芦，不是一个上下差不多粗的柱子。
        path.cubicTo(cx - hw * 1.04, bottom - h * 0.03,
                     cx - hw * 1.05, top + h * 0.89,
                     cx - hw * 1.00, top + h * 0.80)
        # 最宽处 → 脸颊。第二个控制点收到 0.52 制造一个很轻的"腰"，
        # 少了它整只会退化成一个圆锥，看不出头和身体的区别。
        path.cubicTo(cx - hw * 0.96, top + h * 0.50,
                     cx - hw * 0.58, top + h * 0.42,
                     cx - hw * 0.62, top + h * 0.18)
        # 脸颊 → 头顶。末控制点压在 top 上，切线水平，头才是圆的
        path.cubicTo(cx - hw * 0.62, top + h * 0.05,
                     cx - hw * 0.38, top,
                     cx, top)
        # 右半边镜像
        path.cubicTo(cx + hw * 0.38, top,
                     cx + hw * 0.62, top + h * 0.05,
                     cx + hw * 0.62, top + h * 0.18)
        path.cubicTo(cx + hw * 0.58, top + h * 0.42,
                     cx + hw * 0.96, top + h * 0.50,
                     cx + hw * 1.00, top + h * 0.80)
        path.cubicTo(cx + hw * 1.05, top + h * 0.89,
                     cx + hw * 1.04, bottom - h * 0.03,
                     cx + hw * 0.90, bottom)
        # 底部微鼓，坐着的感觉
        path.cubicTo(cx + hw * 0.48, bottom + h * 0.03,
                     cx - hw * 0.48, bottom + h * 0.03,
                     cx - hw * 0.90, bottom)
        path.closeSubpath()
        return path

    def _paint_belly(self, p: QPainter, cx: float, bottom: float, w: float, h: float) -> None:
        """肚子用径向渐变淡出，不描边 —— 参考造型里它是和身体融在一起的。"""
        # 参考造型里肚子几乎占满下半身，是奶油色而不是白色，而且**没有边界** ——
        # 从中心一路淡到透明，靠渐变和身体融在一起。画成不透明的正圆就成了"贴白球"。
        # 关键是**过渡要长**: 参考造型里肚子和身体之间没有边界，是一路淡过去的。
        # 中心不能压满不透明 —— 满不透明 + 短过渡 = 一颗贴在肚子上的发光蛋。
        cy = bottom - h * 0.24
        rx, ry = w * 0.42, h * 0.30
        c, e = self.BELLY, self.BELLY_EDGE
        grad = QRadialGradient(QPointF(cx, cy), max(rx, ry))
        grad.setColorAt(0.00, QColor(c.red(), c.green(), c.blue(), 198))
        grad.setColorAt(0.32, QColor(c.red(), c.green(), c.blue(), 184))
        grad.setColorAt(0.66, QColor(e.red(), e.green(), e.blue(), 112))
        grad.setColorAt(0.88, QColor(e.red(), e.green(), e.blue(), 38))
        grad.setColorAt(1.00, QColor(e.red(), e.green(), e.blue(), 0))
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
        posture: Posture = Posture.RELAXED,
    ) -> None:
        # 肩点埋在身体里，手要能探到轮廓外面 —— 不然只剩两个深色小疙瘩贴在边上。
        # 但手臂别太长: 垂到底会读成脚，参考造型里手是在身体中段的。
        shoulder_y = bottom - h * 0.46
        shoulder_x = w * 0.36
        thickness = w * 0.19
        hand_r = w * 0.115

        if posture is Posture.CROSSED:
            self._draw_crossed_arms(p, cx, shoulder_y, shoulder_x, w, h, thickness, hand_r)
            return

        left, right = self._arm_angles(state, t, facing)
        length = h * 0.22
        thumb = state is State.HAPPY
        self._draw_arm(p, QPointF(cx - shoulder_x, shoulder_y), -1, left, length, thickness, hand_r, thumb)
        self._draw_arm(p, QPointF(cx + shoulder_x, shoulder_y), 1, right, length, thickness, hand_r, thumb)

    def _draw_crossed_arms(
        self, p: QPainter, cx: float, shoulder_y: float, shoulder_x: float,
        w: float, h: float, thickness: float, hand_r: float,
    ) -> None:
        """抱手。

        这个姿势没法用 _arm_angles 那套表达 —— 两条前臂要横过肚子、手落在**对侧**，
        而角度模型只能让手绕着自己那侧的肩转。所以单独一条画法。

        两条手臂必须分先后画，而且**手要伸到对侧的身体边缘**而不是停在正中。
        两只手都落在中间的话会撞成一个蝴蝶结 —— 参考造型里也只清楚露出一只手，
        另一只压在下面。后画的那条自然盖住前一条，前后关系就出来了。
        """
        # 两条前臂要有明显的下垂角度且高度错开，否则会叠成一根横杠，
        # 两端各挂一只手，像鱼鳍。手落在对侧小臂上(而不是身体外缘)才像"抱着"。
        back = (QPointF(cx + shoulder_x, shoulder_y),
                QPointF(cx - w * 0.22, shoulder_y + h * 0.14))
        front = (QPointF(cx - shoulder_x, shoulder_y),
                 QPointF(cx + w * 0.24, shoulder_y + h * 0.21))

        for shoulder, hand in (back, front):
            p.setPen(QPen(self.BODY_MID, thickness, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(shoulder, hand)
            p.setPen(Qt.NoPen)
            # 手指方向不完全跟着小臂: 完全对齐的话两只手会朝左右张开像鸟爪。
            # 把旋转量往竖直方向收一半，指头自然下垂，才像搭在对侧小臂上。
            along = _hand_rotation(hand.x() - shoulder.x(), hand.y() - shoulder.y())
            self._draw_hand(p, hand, hand_r * 0.92, along * 0.5)

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

        if thumb:
            # 握拳 + 竖起的大拇指。拇指画在**屏幕坐标**里始终朝上:
            # 手举到 150° 时如果跟着手臂一起转，拇指会指向斜下方。
            p.setBrush(self.HAND)
            p.drawEllipse(end, hand_r, hand_r * 0.94)
            p.drawRoundedRect(
                QRectF(end.x() - hand_r * 0.26, end.y() - hand_r * 1.95,
                       hand_r * 0.52, hand_r * 1.25),
                hand_r * 0.26, hand_r * 0.26,
            )
            return

        # 手指跟着手臂转，方向才对: 手垂下时朝下，举起来时朝外
        self._draw_hand(p, end, hand_r, -side * angle)

    def _draw_hand(self, p: QPainter, at: QPointF, hand_r: float, rotation: float) -> None:
        """手掌 + 三根手指。rotation 是把手掌局部的 +y 轴对齐到手臂指向的角度。"""
        p.save()
        p.translate(at)
        p.rotate(rotation)
        # 手指和手掌同色、只靠两道指缝分开。用更深的颜色画实心手指的话，
        # 在这个尺寸下会读成三只爪子而不是一只手。
        p.setBrush(self.HAND)
        p.drawEllipse(QPointF(0, -hand_r * 0.18), hand_r * 0.94, hand_r * 0.80)
        for k in (-1.0, 0.0, 1.0):
            p.drawRoundedRect(
                QRectF(k * hand_r * 0.50 - hand_r * 0.21, hand_r * 0.02,
                       hand_r * 0.42, hand_r * 0.72),
                hand_r * 0.21, hand_r * 0.21,
            )
        p.setPen(QPen(self.HAND_DEEP, hand_r * 0.09, Qt.SolidLine, Qt.RoundCap))
        for k in (-0.5, 0.5):
            p.drawLine(QPointF(k * hand_r * 1.00, hand_r * 0.14),
                       QPointF(k * hand_r * 1.00, hand_r * 0.62))
        p.setPen(Qt.NoPen)
        p.restore()

    # --- 表情 -------------------------------------------------------------
    def _paint_face(
        self, p: QPainter, state: State, t: float, facing: int,
        cx: float, bottom: float, w: float, h: float,
    ) -> None:
        eye_y = bottom - h * 0.80
        gap = w * 0.145
        shift = facing * w * 0.026          # 眼睛朝行进方向偏一点
        if state is State.CLING:
            shift = -shift                  # 挂墙上时往屏幕内侧瞟
        left = QPointF(cx - gap + shift, eye_y)
        right = QPointF(cx + gap + shift, eye_y)
        r = w * 0.078

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

        self._paint_mouth(p, state, cx + shift, eye_y + r * 2.4, w)

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
        # 参考造型的嘴是一条**很宽很浅**的弧，几乎横贯脸部。
        # 画窄了会变成噘嘴，是这只角色最容易画丢的特征之一。
        half = w * 0.115
        depth = w * 0.045
        if state is State.HAPPY:
            half, depth = w * 0.135, w * 0.080
        elif state is State.SLEEP:
            half, depth = w * 0.070, w * 0.022
        elif state is State.DIZZY:
            depth = -depth * 0.7            # 往下撇
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

    def _paint_hearts(self, p: QPainter, cx: float, t: float) -> None:
        ceiling = self.size * 0.055        # 画布留白，爱心飘到这儿为止
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
            p.drawPath(_heart_path(
                cx + drift + (i - 1) * 15,
                ceiling + (1.0 - phase) * self.size * 0.11,
                3.2 + phase * 2.2,
            ))

    def _paint_stars(self, p: QPainter, cx: float, t: float) -> None:
        """三颗星星绕着头顶转圈 —— 椭圆轨道，看起来才有透视。"""
        cy = self.size * 0.13
        p.setPen(Qt.NoPen)
        p.setBrush(self.STAR)
        for i in range(3):
            a = t * 5.0 + i * (2 * math.pi / 3)
            p.drawPath(_sparkle_path(cx + math.cos(a) * 19, cy + math.sin(a) * 5, 4.5))


def _hand_rotation(dx: float, dy: float) -> float:
    """把手掌局部的 +y 轴转到 (dx, dy) 方向所需的角度(度，Qt 顺时针为正)。

    (0,1) 顺时针转 θ 得到 (-sinθ, cosθ)，令它等于方向向量即得 atan2(-dx, dy)。
    """
    return math.degrees(math.atan2(-dx, dy))


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

    resizable = False       # 尺寸由素材本身决定，缩放会糊

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

    def render(
        self, state: State, t: float, facing: int, dpr: float = 1.0,
        posture: Posture = Posture.RELAXED,
    ) -> QImage:
        # posture 收下但不用: 位图素材没有"抱手"这一帧，硬凑只会更怪。
        # 想要的话按 sprites/idle/ 的约定自己画一套就行。
        del posture
        # 缺哪个状态就退回 idle，素材可以一个状态一个状态地补
        seq = self.frames.get(state.value) or self.frames.get(State.IDLE.value)
        if not seq:
            return QImage()
        img = seq[int(t * SPRITE_FPS) % len(seq)]
        if facing < 0:
            img = img.mirrored(True, False)
        return img


def pick_provider(sprites_dir: Path, size: int = PET_SIZE):
    """有素材就用素材，没有就用现画的。

    size 只对现画的角色生效 —— 位图素材的尺寸由素材自己决定，
    缩放只会糊掉，配置里的大小对它没有意义。
    """
    if sprites_dir.is_dir():
        folder = FolderSprites(sprites_dir)
        if folder.has_frames():
            return folder
    pet = BlobPet()
    pet.size = size
    return pet
