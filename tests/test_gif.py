"""GIF 编码器的测试：写出去，再用 **Qt 自己的解码器**读回来逐帧比对。

这是这个编码器唯一靠得住的验证方式。LZW 的码长切换点差一位，
前几百个码还是对的、之后全乱 —— 看代码看不出来，肉眼看缩略图也未必看得出来，
只有让一个独立实现的解码器把它解回来才算数。

    python -m unittest discover
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage, QImageReader  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from tools.gif import lzw_encode, write_gif  # noqa: E402

W, H = 24, 16
_app = None


def setUpModule() -> None:
    global _app
    _app = QApplication.instance() or QApplication([])


def solid(r: int, g: int, b: int) -> bytes:
    return bytes((r, g, b)) * (W * H)


def gradient(shift: int) -> bytes:
    """有渐变才会逼出调色板量化，纯色测不到。"""
    out = bytearray()
    for y in range(H):
        for x in range(W):
            out += bytes((((x * 9 + shift) % 256), ((y * 13) % 256), 128))
    return bytes(out)


def decode(path: Path) -> list[QImage]:
    reader = QImageReader(str(path))
    frames = []
    while True:
        img = reader.read()
        if img.isNull():
            break
        frames.append(img.convertToFormat(QImage.Format_RGB888).copy())
    return frames


class GifCase(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.path = Path(self._dir.name) / "out.gif"

    def tearDown(self) -> None:
        self._dir.cleanup()

    def assert_close(self, image: QImage, expected: bytes, tolerance: int = 12) -> None:
        """量化必然引入误差，所以比的是接近而不是相等。"""
        for y in range(H):
            for x in range(W):
                i = (y * W + x) * 3
                got = image.pixelColor(x, y)
                for channel, want in zip((got.red(), got.green(), got.blue()), expected[i:i + 3]):
                    self.assertLessEqual(abs(channel - want), tolerance, f"({x},{y})")


class TestRoundTrip(GifCase):
    def test_qt_can_read_what_we_wrote(self):
        write_gif(self.path, [solid(200, 40, 60)], W, H)
        frames = decode(self.path)
        self.assertEqual(len(frames), 1)
        self.assert_close(frames[0], solid(200, 40, 60))

    def test_frame_count_survives(self):
        write_gif(self.path, [gradient(s) for s in (0, 40, 80, 120, 160)], W, H)
        self.assertEqual(len(decode(self.path)), 5)

    def test_gradients_survive_quantisation(self):
        source = gradient(0)
        write_gif(self.path, [source], W, H)
        self.assert_close(decode(self.path)[0], source)

    def test_every_frame_matches_its_source(self):
        """帧间差分只编码变化的矩形，合成错了这里就会露馅。"""
        sources = [gradient(s) for s in (0, 55, 110, 165)]
        write_gif(self.path, sources, W, H)
        frames = decode(self.path)
        self.assertEqual(len(frames), len(sources))
        for i, (image, source) in enumerate(zip(frames, sources)):
            with self.subTest(frame=i):
                self.assert_close(image, source)

    def test_size_is_preserved(self):
        write_gif(self.path, [solid(10, 20, 30)], W, H)
        image = decode(self.path)[0]
        self.assertEqual((image.width(), image.height()), (W, H))

    def test_identical_frames_still_decode(self):
        """完全没变化的帧：差分矩形是空的，得退化成 1x1 而不是 0 尺寸。"""
        frame = solid(90, 90, 90)
        write_gif(self.path, [frame, frame, frame], W, H)
        frames = decode(self.path)
        self.assertEqual(len(frames), 3)
        for image in frames:
            self.assert_close(image, frame)


class TestFormat(GifCase):
    def test_is_recognised_as_an_animation(self):
        write_gif(self.path, [gradient(0), gradient(90)], W, H)
        reader = QImageReader(str(self.path))
        self.assertEqual(bytes(reader.format()).decode(), "gif")
        self.assertTrue(reader.supportsAnimation())

    def test_loops_forever_by_default(self):
        write_gif(self.path, [gradient(0), gradient(90)], W, H)
        self.assertIn(b"NETSCAPE2.0", self.path.read_bytes())

    def test_ends_with_the_trailer(self):
        write_gif(self.path, [solid(1, 2, 3)], W, H)
        self.assertEqual(self.path.read_bytes()[-1], 0x3B)

    def test_rejects_an_empty_animation(self):
        with self.assertRaises(ValueError):
            write_gif(self.path, [], W, H)


class TestLzw(unittest.TestCase):
    def test_starts_with_a_clear_code(self):
        # 最小码长 2 时清除码是 4，占低 3 位 -> 第一个字节的低 3 位应该是 100
        data = lzw_encode(bytes([0, 1, 2, 3]), 2)
        self.assertEqual(data[0] & 0b111, 4)

    def test_long_runs_compress(self):
        """一万个相同像素要是没被压到很小，说明字典根本没建起来。"""
        data = lzw_encode(bytes([7]) * 10000, 8)
        self.assertLess(len(data), 500)


if __name__ == "__main__":
    unittest.main()
