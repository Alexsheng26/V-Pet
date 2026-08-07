"""渲染层的测试。需要 Qt，但用 offscreen 平台跑，不需要显示器。

    python -m unittest discover
"""

from __future__ import annotations

import os
import unittest

# 必须在 import QtGui 之前设好，否则 CI / 无桌面环境会起不来
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage  # noqa: E402

# 必须是 QApplication 而不是 QGuiApplication: 同一个进程只能有一个 app 实例，
# 而 test_window_config 里的 QWidget 需要 QApplication。这里若先建了
# QGuiApplication，那边 instance() 拿到的就是它，创建窗口时直接段错误。
from PySide6.QtWidgets import QApplication  # noqa: E402

from vpet.render import PET_SIZE, BlobPet, pose_for  # noqa: E402
from vpet.state import Posture, State  # noqa: E402

_app: QApplication | None = None


def setUpModule() -> None:
    global _app
    _app = QApplication.instance() or QApplication([])


def logical_bbox(img, threshold: int = 8) -> tuple[float, float, float, float] | None:
    """宠物在**逻辑坐标**下的包围盒。不同 dpr 下它应该一致。

    转成 Alpha8 后直接扫原始字节。逐像素调 pixelColor() 也能得到同样结果，
    但这个函数要跑 120 张图，那样整个测试套件会从 1 秒涨到 10 秒。
    """
    alpha = img.convertToFormat(QImage.Format_Alpha8)
    w, h = alpha.width(), alpha.height()
    stride = alpha.bytesPerLine()
    buf = bytes(alpha.constBits())

    left, top, right, bottom = w, h, -1, -1
    for y in range(h):
        row = buf[y * stride: y * stride + w]
        if max(row) <= threshold:
            continue
        first = next(i for i, v in enumerate(row) if v > threshold)
        last = w - 1 - next(i for i, v in enumerate(reversed(row)) if v > threshold)
        left, right = min(left, first), max(right, last)
        if top == h:
            top = y
        bottom = y
    if bottom < 0:
        return None

    dpr = img.devicePixelRatio()
    return (left / dpr, top / dpr, right / dpr, bottom / dpr)


class TestDevicePixelRatio(unittest.TestCase):
    """回归测试。

    曾经在 render() 里写了 p.scale(dpr, dpr)，但 QPainter 作用在设过
    devicePixelRatio 的 QImage 上时会**自己**应用缩放，于是被乘了两次。
    在 100% 缩放的屏幕上(dpr=1)完全看不出来，一到 150% 宠物就被裁边。
    """

    def test_physical_size_scales_with_dpr(self):
        pet = BlobPet()
        for dpr in (1.0, 1.5, 2.0):
            img = pet.render(State.IDLE, 0.5, 1, dpr)
            self.assertEqual(img.width(), int(PET_SIZE * dpr))
            self.assertEqual(img.devicePixelRatio(), dpr)

    def test_logical_size_is_identical_across_dpr(self):
        pet = BlobPet()
        boxes = {}
        for dpr in (1.0, 1.5, 2.0):
            box = logical_bbox(pet.render(State.IDLE, 0.5, 1, dpr))
            self.assertIsNotNone(box, f"dpr={dpr} 渲染出了空图")
            boxes[dpr] = box

        base = boxes[1.0]
        for dpr, box in boxes.items():
            for got, want, axis in zip(box, base, "左上右下"):
                self.assertAlmostEqual(
                    got, want, delta=2.0,
                    msg=f"dpr={dpr} 的{axis}边界是 {got:.1f}，dpr=1 时是 {want:.1f}",
                )

    def test_nothing_touches_the_canvas_edge(self):
        """比"没出界"更严: 碰到边缘就说明已经被裁掉了一部分。

        裁掉的部分在包围盒里看不出来(它只会停在 0 或 PET_SIZE)，
        所以必须留一点余量来反推。手举过头、爱心和星星最容易顶出去。
        """
        pet = BlobPet()
        margin = 0.5
        combos = [(s, Posture.RELAXED) for s in State] + [(State.IDLE, Posture.CROSSED)]
        for dpr in (1.0, 1.5, 2.0):
            for state, posture in combos:
                for t in (0.2, 0.55, 0.95, 1.4, 1.85):
                    box = logical_bbox(pet.render(state, t, 1, dpr, posture))
                    self.assertIsNotNone(box)
                    left, top, right, bottom = box
                    where = f"{state.value}/{posture.value} @t={t} dpr={dpr}"
                    self.assertGreaterEqual(left, margin, f"{where} 左边贴边")
                    self.assertGreaterEqual(top, margin, f"{where} 上边贴边")
                    self.assertLessEqual(right, PET_SIZE - margin, f"{where} 右边贴边")
                    self.assertLessEqual(bottom, PET_SIZE - margin, f"{where} 下边贴边")


class TestStates(unittest.TestCase):
    def test_every_state_renders_something(self):
        pet = BlobPet()
        for state in State:
            for t in (0.0, 0.7, 1.9, 3.35):     # 3.35 落在眨眼窗口里
                img = pet.render(state, t, -1, 1.0)
                self.assertFalse(img.isNull(), f"{state.value} @t={t}")
                self.assertIsNotNone(logical_bbox(img), f"{state.value} @t={t} 画了个空的")

    def test_only_cling_and_dizzy_tilt(self):
        upright = {s for s in State if pose_for(s, 0.9, 1).rot == 0.0}
        self.assertEqual(upright, set(State) - {State.CLING, State.DIZZY})

    def test_crossed_posture_actually_looks_different(self):
        pet = BlobPet()
        relaxed = pet.render(State.IDLE, 0.5, 1, 1.0, Posture.RELAXED)
        crossed = pet.render(State.IDLE, 0.5, 1, 1.0, Posture.CROSSED)
        self.assertNotEqual(relaxed, crossed)

    def test_posture_defaults_to_relaxed(self):
        pet = BlobPet()
        self.assertEqual(
            pet.render(State.IDLE, 0.5, 1, 1.0),
            pet.render(State.IDLE, 0.5, 1, 1.0, Posture.RELAXED),
        )

    def test_cling_leans_toward_the_wall_it_hangs_on(self):
        # facing=1 表示挂在左墙上、脸朝屏幕内侧，身体该往左蹭
        self.assertLess(pose_for(State.CLING, 0.0, 1).dx, 0)
        self.assertGreater(pose_for(State.CLING, 0.0, -1).dx, 0)


if __name__ == "__main__":
    unittest.main()
