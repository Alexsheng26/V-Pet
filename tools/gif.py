"""一个最小的 GIF89a 编码器：中位切分调色板 + LZW + 帧间差分。

为什么手写：README 要一张动图，而 **Qt 只能读 GIF 不能写**，标准库也没有。
唯一的现成方案是引入 Pillow —— 为了一张文档配图给项目加一个依赖不划算。
和 tools/make_icon.py 手写 ICO 头是同一个取舍。

正确性不靠肉眼：`tests/test_gif.py` 用 Qt 自己的 GIF **读取器**把产物解回来逐帧
比对像素。LZW 的码长切换点差一位，解出来就是花屏 —— 这种错误看代码看不出来，
必须让解码器来判。
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

MAX_COLOURS = 256
_LZW_MAX = 4096


# --- 调色板 ---------------------------------------------------------------
def _key(r: int, g: int, b: int) -> int:
    """每通道压到 5 bit 当直方图的桶。

    不压的话 1600 万个桶，中位切分会慢到没法用；压到 5 bit 只有 32768 个，
    而这动图的颜色本来就集中在一小片黄色里，肉眼看不出差别。
    """
    return ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)


def _unkey(key: int) -> tuple[int, int, int]:
    # 5 bit 还原成 8 bit：高位补到低位，才能让 31 还原成 255 而不是 248
    parts = ((key >> 10) & 31, (key >> 5) & 31, key & 31)
    return tuple((v << 3) | (v >> 2) for v in parts)  # type: ignore[return-value]


def _channel(key: int, ch: int) -> int:
    return (key >> (10 - 5 * ch)) & 31


def _median_cut(hist: dict[int, int], colours: int) -> tuple[list[tuple[int, int, int]], dict[int, int]]:
    """把直方图切成 <=colours 个盒子，每个盒子出一个代表色。

    返回 (调色板, 桶 -> 调色板下标)。因为每个桶恰好属于一个盒子，
    映射是精确的，不需要再做最近邻搜索。
    """
    boxes: list[list[int]] = [list(hist)]
    while len(boxes) < colours:
        # 挑"颜色跨度 × 像素数"最大的盒子切 —— 只看跨度会把大片纯色区域饿死
        target, best = -1, -1.0
        for i, box in enumerate(boxes):
            if len(box) < 2:
                continue
            spread = max(
                max(_channel(k, c) for k in box) - min(_channel(k, c) for k in box)
                for c in range(3)
            )
            score = spread * sum(hist[k] for k in box)
            if score > best:
                target, best = i, score
        if target < 0:
            break                       # 每个盒子都只剩一种颜色，切不动了
        box = boxes[target]
        widest = max(
            range(3),
            key=lambda c: max(_channel(k, c) for k in box) - min(_channel(k, c) for k in box),
        )
        box.sort(key=lambda k: _channel(k, widest))
        mid = len(box) // 2
        boxes[target], _ = box[:mid], None
        boxes.append(box[mid:])

    palette: list[tuple[int, int, int]] = []
    lookup: dict[int, int] = {}
    for index, box in enumerate(boxes):
        weight = sum(hist[k] for k in box) or 1
        acc = [0, 0, 0]
        for k in box:
            r, g, b = _unkey(k)
            n = hist[k]
            acc[0] += r * n
            acc[1] += g * n
            acc[2] += b * n
            lookup[k] = index
        palette.append((acc[0] // weight, acc[1] // weight, acc[2] // weight))
    return palette, lookup


# --- LZW ------------------------------------------------------------------
class _Bits:
    """GIF 的位流是 **LSB 优先**的，和直觉相反，写反了解码器直接读出噪声。"""

    def __init__(self) -> None:
        self.data = bytearray()
        self._acc = 0
        self._bits = 0

    def write(self, code: int, size: int) -> None:
        self._acc |= code << self._bits
        self._bits += size
        while self._bits >= 8:
            self.data.append(self._acc & 0xFF)
            self._acc >>= 8
            self._bits -= 8

    def flush(self) -> bytes:
        if self._bits:
            self.data.append(self._acc & 0xFF)
            self._acc = self._bits = 0
        return bytes(self.data)


def lzw_encode(indices: bytes, min_code_size: int) -> bytes:
    clear = 1 << min_code_size
    end = clear + 1
    bits = _Bits()

    table: dict[tuple[int, ...], int] = {}
    next_code = code_size = 0

    def reset() -> None:
        nonlocal table, next_code, code_size
        table = {(i,): i for i in range(clear)}
        next_code = end + 1
        code_size = min_code_size + 1

    reset()
    bits.write(clear, code_size)

    buffer: tuple[int, ...] = ()
    for pixel in indices:
        candidate = buffer + (pixel,)
        if candidate in table:
            buffer = candidate
            continue
        bits.write(table[buffer], code_size)
        if next_code < _LZW_MAX:
            table[candidate] = next_code
            next_code += 1
            # 必须是 > 而不是 ==。解码器的字典**比编码器慢一步**建起来，
            # 用 == 的话编码器会早一个码加宽，那一个码上编码器写 n+1 位、
            # 解码器只读 n 位，从此彻底失步（表现是前几个像素正确、之后全是噪声）。
            # 晚一个码加宽是安全的：新建的那个码至少要再过一轮才可能被发出去，
            # 那时候宽度已经加上了。
            if next_code > (1 << code_size) and code_size < 12:
                code_size += 1
        else:
            bits.write(clear, code_size)
            reset()
        buffer = (pixel,)

    if buffer:
        bits.write(table[buffer], code_size)
    bits.write(end, code_size)
    return bits.flush()


def _sub_blocks(payload: bytes) -> bytes:
    """GIF 的数据段按 <=255 字节分块，每块前面一个长度字节，0 收尾。"""
    out = bytearray()
    for i in range(0, len(payload), 255):
        chunk = payload[i:i + 255]
        out.append(len(chunk))
        out += chunk
    out.append(0)
    return bytes(out)


# --- 组装 ------------------------------------------------------------------
def _diff_rect(a: bytes, b: bytes, width: int, height: int) -> tuple[int, int, int, int]:
    """两帧之间真正变了的最小矩形。

    背景是不动的，只有宠物那一小块在变。整帧编码的话体积是这个的好几倍。
    """
    top, bottom = height, -1
    left, right = width, -1
    for y in range(height):
        row = y * width
        if a[row:row + width] == b[row:row + width]:
            continue
        top = min(top, y)
        bottom = y
        for x in range(width):
            if a[row + x] != b[row + x]:
                left = min(left, x)
                break
        for x in range(width - 1, -1, -1):
            if a[row + x] != b[row + x]:
                right = max(right, x)
                break
    if bottom < 0:
        return 0, 0, 1, 1               # 完全没变；GIF 不接受 0 尺寸的帧
    return left, top, right - left + 1, bottom - top + 1


def write_gif(
    path: str | Path,
    frames: Sequence[bytes],
    width: int,
    height: int,
    delay_cs: int = 8,
    loop: int = 0,
) -> int:
    """frames 是每帧 width*height*3 字节的 RGB。返回文件大小。"""
    if not frames:
        raise ValueError("没有帧")

    hist: dict[int, int] = {}
    for frame in frames:
        for i in range(0, len(frame), 3):
            k = _key(frame[i], frame[i + 1], frame[i + 2])
            hist[k] = hist.get(k, 0) + 1
    palette, lookup = _median_cut(hist, MAX_COLOURS)

    indexed = [
        bytes(lookup[_key(f[i], f[i + 1], f[i + 2])] for i in range(0, len(f), 3))
        for f in frames
    ]

    # 调色板大小必须是 2 的幂，不足的补黑
    bits_per_pixel = max(1, (len(palette) - 1).bit_length())
    table_size = 1 << bits_per_pixel
    table = bytearray()
    for r, g, b in palette:
        table += bytes((r, g, b))
    table += bytes(3 * (table_size - len(palette)))

    out = bytearray(b"GIF89a")
    out += width.to_bytes(2, "little") + height.to_bytes(2, "little")
    out.append(0xF0 | (bits_per_pixel - 1))     # 有全局调色板
    out += bytes((0, 0))
    out += table
    # NETSCAPE2.0 扩展，唯一的循环播放方式
    out += b"\x21\xFF\x0BNETSCAPE2.0\x03\x01" + loop.to_bytes(2, "little") + b"\x00"

    previous: bytes | None = None
    for frame in indexed:
        if previous is None:
            x = y = 0
            w, h = width, height
            patch = frame
        else:
            x, y, w, h = _diff_rect(previous, frame, width, height)
            patch = b"".join(frame[(y + r) * width + x:(y + r) * width + x + w] for r in range(h))
        # 处置方式 1 = 画完留在原地，后面的差分帧才能叠上去
        out += b"\x21\xF9\x04\x04" + delay_cs.to_bytes(2, "little") + b"\x00\x00"
        out += b"\x2C"
        out += x.to_bytes(2, "little") + y.to_bytes(2, "little")
        out += w.to_bytes(2, "little") + h.to_bytes(2, "little")
        out.append(0)                            # 用全局调色板，非交错
        out.append(max(2, bits_per_pixel))       # LZW 最小码长下限是 2
        out += _sub_blocks(lzw_encode(patch, max(2, bits_per_pixel)))
        previous = frame

    out.append(0x3B)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))
    return len(out)
