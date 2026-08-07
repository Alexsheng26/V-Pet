"""渲染层的测试。需要 Qt，但用 offscreen 平台跑，不需要显示器。

    python -m unittest discover
"""

from __future__ import annotations

import os
import unittest

# 必须在 import QtGui 之前设好，否则 CI / 无桌面环境会起不来
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication  # noqa: E402

from vpet.render import PET_SIZE, ProceduralPet, pose_for  # noqa: E402
from vpet.state import State  # noqa: E402

_app: QGuiApplication | None = None


def setUpModule() -> None:
    global _app
    _app = QGuiApplication.instance() or QGuiApplication([])


def logical_bbox(img, threshold: int = 8) -> tuple[float, float, float, float] | None:
    """宠物在**逻辑坐标**下的包围盒。不同 dpr 下它应该一致。"""
    dpr = img.devicePixelRatio()
    xs, ys = [], []
    for y in range(img.height()):
        for x in range(img.width()):
            if img.pixelColor(x, y).alpha() > threshold:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return (min(xs) / dpr, min(ys) / dpr, max(xs) / dpr, max(ys) / dpr)


class TestDevicePixelRatio(unittest.TestCase):
    """回归测试。

    曾经在 render() 里写了 p.scale(dpr, dpr)，但 QPainter 作用在设过
    devicePixelRatio 的 QImage 上时会**自己**应用缩放，于是被乘了两次。
    在 100% 缩放的屏幕上(dpr=1)完全看不出来，一到 150% 宠物就被裁边。
    """

    def test_physical_size_scales_with_dpr(self):
        pet = ProceduralPet()
        for dpr in (1.0, 1.5, 2.0):
            img = pet.render(State.IDLE, 0.5, 1, dpr)
            self.assertEqual(img.width(), int(PET_SIZE * dpr))
            self.assertEqual(img.devicePixelRatio(), dpr)

    def test_logical_size_is_identical_across_dpr(self):
        pet = ProceduralPet()
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

    def test_pet_stays_inside_the_window(self):
        pet = ProceduralPet()
        for dpr in (1.0, 1.5, 2.0):
            for state in State:
                box = logical_bbox(pet.render(state, 0.5, 1, dpr))
                self.assertIsNotNone(box)
                left, top, right, bottom = box
                self.assertGreaterEqual(left, 0)
                self.assertGreaterEqual(top, 0)
                self.assertLessEqual(right, PET_SIZE, f"{state.value} @dpr={dpr} 右边出界")
                self.assertLessEqual(bottom, PET_SIZE, f"{state.value} @dpr={dpr} 下边出界")


class TestStates(unittest.TestCase):
    def test_every_state_renders_something(self):
        pet = ProceduralPet()
        for state in State:
            for t in (0.0, 0.7, 1.9, 3.35):     # 3.35 落在眨眼窗口里
                img = pet.render(state, t, -1, 1.0)
                self.assertFalse(img.isNull(), f"{state.value} @t={t}")
                self.assertIsNotNone(logical_bbox(img), f"{state.value} @t={t} 画了个空的")

    def test_only_cling_and_dizzy_tilt(self):
        upright = {s for s in State if pose_for(s, 0.9, 1).rot == 0.0}
        self.assertEqual(upright, set(State) - {State.CLING, State.DIZZY})

    def test_cling_leans_toward_the_wall_it_hangs_on(self):
        # facing=1 表示挂在左墙上、脸朝屏幕内侧，身体该往左蹭
        self.assertLess(pose_for(State.CLING, 0.0, 1).dx, 0)
        self.assertGreater(pose_for(State.CLING, 0.0, -1).dx, 0)


if __name__ == "__main__":
    unittest.main()
