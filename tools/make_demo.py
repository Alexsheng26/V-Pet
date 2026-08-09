"""生成 README 用的演示动图。

    python tools/make_demo.py docs/demo.gif

驱动的是**真实的 PetBrain** —— 重力、反弹、摔懵判定、抱手概率全是产品代码算出来的，
这里只负责在特定时刻喂进"抓起来 / 松手 / 摸头"这些输入，等于把用户操作录了一遍。
所以这张图跑出来什么样，程序跑起来就是什么样。

以 60fps 模拟、每 5 帧取一张输出：拖拽速度是按相邻两帧的位移反推的，
直接按 12fps 模拟的话甩不出足够的速度，摔不懵。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRectF, Qt                                    # noqa: E402
from PySide6.QtGui import (                                             # noqa: E402
    QColor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter,
)

from tools.gif import write_gif                                          # noqa: E402
from vpet.render import BlobPet                                          # noqa: E402
from vpet.screens import ScreenLayout                                    # noqa: E402
from vpet.state import PetBrain, Posture, State                          # noqa: E402

WIDTH, HEIGHT = 520, 380
TASKBAR = 42
PET = 104
SIM_FPS, EVERY = 60, 5           # 输出 12fps

# (字幕, 持续秒数, 进入时的动作)
# 用显式的阶段机而不是一串 `elif t < 2.95`：后者靠"某一帧恰好落进这个窗口"生效，
# 改一下帧率或者时长就会静默地漏掉一个动作。
SCRIPT = [
    ("发呆 · 呼吸", 1.0, None),
    ("溜达", 1.3, "walk"),
    ("抓起来", 0.75, "lift"),
    ("往下甩", 0.05, "flick"),      # 只要 3 帧：速度是按相邻帧位移反推的，攒得很快
    ("松手 · 落地反弹", 2.4, "release"),
    ("摸头", 2.0, "pat"),
    ("抱手待机", 1.8, "cross"),
    ("睡着了", 1.4, "sleep"),
]

DESKTOP_TOP = QColor(38, 44, 56)
DESKTOP_BOTTOM = QColor(24, 28, 36)
BAR = QColor(18, 21, 27)
ICON = QColor(70, 80, 96)
CAPTION = QColor(196, 206, 220)


def build_background() -> QImage:
    img = QImage(WIDTH, HEIGHT, QImage.Format_RGB888)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)

    grad = QLinearGradient(0, 0, 0, HEIGHT)
    grad.setColorAt(0.0, DESKTOP_TOP)
    grad.setColorAt(1.0, DESKTOP_BOTTOM)
    p.fillRect(0, 0, WIDTH, HEIGHT, grad)

    # 一条模拟任务栏 + 几个方块当图标：给宠物一个"站在哪儿"的参照，
    # 也顺便说明它是站在任务栏上沿而不是被任务栏盖住的
    p.fillRect(0, HEIGHT - TASKBAR, WIDTH, TASKBAR, BAR)
    p.setPen(Qt.NoPen)
    p.setBrush(ICON)
    for i in range(5):
        p.drawRoundedRect(QRectF(16 + i * 34, HEIGHT - TASKBAR + 12, 20, 18), 4, 4)
    p.end()
    return img


class Demo:
    """按剧本喂输入，其余交给 PetBrain。"""

    def __init__(self) -> None:
        self.pet = BlobPet()
        self.pet.size = PET
        # 屏幕的"可用区域"排除任务栏，和真实程序一致
        self.brain = PetBrain(PET, ScreenLayout.single((0, 0, WIDTH, HEIGHT - TASKBAR)))
        self.background = build_background()
        self.caption = ""
        self.phase = 0
        self.phase_t = 0.0
        self.entered = False

    # --- 剧本 ---------------------------------------------------------
    def act(self, dt: float) -> None:
        caption, duration, action = SCRIPT[self.phase]
        # 摔懵是物理算出来的、不是剧本安排的，所以字幕跟着实际状态走 ——
        # 万一哪天调参把冲击调到阈值以下，图上就不会再出现这句，而不是撒谎
        self.caption = "摔懵了" if self.brain.state is State.DIZZY else caption
        if not self.entered:
            self._enter_phase(action)
            self.entered = True
        self._hold(action, dt)

        self.phase_t += dt
        if self.phase_t >= duration and self.phase + 1 < len(SCRIPT):
            self.phase += 1
            self.phase_t = 0.0
            self.entered = False

    def _enter_phase(self, action: str | None) -> None:
        b = self.brain
        if action == "walk":
            b._enter(State.WALK)
            b.next_switch = 99.0            # 别让随机时长打断演示
            b.vx = abs(b.vx)
        elif action == "lift":
            b.grab()
        elif action == "release":
            b.release()
        elif action == "pat":
            b.head_pat()
        elif action == "cross":
            b._enter(State.IDLE)
            b.posture = Posture.CROSSED
            b.next_switch = 99.0
        elif action == "sleep":
            b.doze_off()

    def _hold(self, action: str | None, dt: float) -> None:
        b = self.brain
        if action == "lift":
            b.drag_to(b.x + 120 * dt, max(6.0, b.y - 340 * dt))
        elif action == "flick":
            # 关键在**松手时还得留够下落高度**：冲击是 sqrt(v² + 2gh)，
            # 松手速度被 THROW_LIMIT 卡在 900，光靠它到不了摔懵的 1100，
            # 差的那部分得靠自由落体补。甩过头把宠物直接甩到地面以下的话，
            # h 就是 0，怎么甩都懵不了 —— 第一版就是这么写错的。
            b.drag_to(b.x - 30 * dt, b.y + 1400 * dt)

    # --- 渲染 ---------------------------------------------------------
    def compose(self, t: float) -> bytes:
        canvas = self.background.copy()
        p = QPainter(canvas)
        p.setRenderHint(QPainter.Antialiasing)

        frame = self.pet.render(self.brain.state, t, self.brain.facing, 1.0, self.brain.posture)
        p.drawImage(round(self.brain.x), round(self.brain.y), frame)

        p.setFont(QFont("Microsoft YaHei UI", 12))
        p.setPen(CAPTION)
        p.drawText(QRectF(18, 12, WIDTH - 36, 26), Qt.AlignLeft | Qt.AlignVCenter, self.caption)
        p.end()

        rgb = canvas.convertToFormat(QImage.Format_RGB888)
        stride = rgb.bytesPerLine()
        raw = bytes(rgb.constBits())
        # bytesPerLine 可能带对齐填充，必须按行裁掉
        return b"".join(raw[y * stride: y * stride + WIDTH * 3] for y in range(HEIGHT))

    def run(self) -> tuple[list[bytes], dict]:
        dt = 1.0 / SIM_FPS
        frames: list[bytes] = []
        seen: set[str] = set()
        peak = 0.0
        total = sum(d for _, d, _ in SCRIPT)
        for step in range(int(total * SIM_FPS)):
            self.act(dt)
            self.brain.update(dt)
            seen.add(self.brain.state.value)
            if self.brain.posture is Posture.CROSSED:
                seen.add("crossed")
            peak = max(peak, self.brain._impact)
            if step % EVERY == 0:
                frames.append(self.compose(step * dt))
        return frames, {"seen": seen, "impact": peak}


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/demo.gif")
    QGuiApplication.instance() or QGuiApplication([])

    frames, report = Demo().run()
    size = write_gif(out, frames, WIDTH, HEIGHT, delay_cs=100 // (SIM_FPS // EVERY))

    print(f"{out}  {WIDTH}x{HEIGHT}  {len(frames)} 帧  {size / 1024:.0f} KB")
    print(f"落地冲击峰值 {report['impact']:.0f}（摔懵阈值 1100）")
    want = {"idle", "walk", "drag", "fall", "dizzy", "happy", "crossed", "sleep"}
    missing = want - report["seen"]
    print("演示覆盖: " + ("全部状态都出现了 ✓" if not missing else f"少了 {sorted(missing)} ✗"))
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
