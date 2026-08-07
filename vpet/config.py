"""配置持久化。

和 state.py 一样**不 import Qt**：这里只管把一堆值可靠地存进磁盘、再读回来，
"这个坐标在不在屏幕上"是窗口层的事(它才知道有几块屏幕)。

三条硬要求，都是为了"宠物永远能起来"：

1. **原子写**：先写同目录下的临时文件，再 os.replace 换过去。直接 open(path,"w")
   的话，写到一半断电/崩溃就会留下半个 JSON，下次启动直接读不出来。

2. **容错读**：文件缺失、内容损坏、字段少了、字段多了、类型不对，一律退回默认值，
   绝不抛异常。一个因为配置文件坏了就打不开的桌宠是没法用的 ——
   而且它连个报错窗口都没有，用户只会觉得"点了没反应"。

3. **字段按名字逐个取**：少了的用默认值(旧版本配置能被新版本读)，
   多了的直接忽略(新版本写的配置回退到旧版本也能读)。
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path

APP_NAME = "v-pet"
CONFIG_VERSION = 1

DEFAULT_SIZE = 144
SIZE_CHOICES = (96, 120, 144, 176, 208)
MIN_SIZE, MAX_SIZE = 64, 320


def config_path() -> Path:
    """Windows 放 %APPDATA%\\v-pet\\，其它平台放 ~/.config/v-pet/。"""
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    return root / APP_NAME / "config.json"


@dataclass
class Config:
    x: int | None = None          # 窗口左上角。None = 还没存过，用默认位置
    y: int | None = None
    size: int = DEFAULT_SIZE
    follow: bool = False
    autostart: bool = False

    # --- 读 ---------------------------------------------------------------
    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        path = path or config_path()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()                     # 不存在 / 不是合法 JSON
        if not isinstance(raw, dict):
            return cls()                     # 是合法 JSON 但不是对象，比如 "[]"
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict) -> Config:
        cfg = cls()
        for field in fields(cls):
            if field.name in raw:            # 少了就保留默认值
                setattr(cfg, field.name, raw[field.name])
        cfg.normalise()                      # 多出来的键在这一步之前就被忽略了
        return cfg

    def normalise(self) -> None:
        """把任何读进来的脏值收拾成可用的值。手改过配置文件也不该炸。"""
        self.x = _opt_int(self.x)
        self.y = _opt_int(self.y)
        self.size = _clamp_int(self.size, MIN_SIZE, MAX_SIZE, DEFAULT_SIZE)
        self.follow = _as_bool(self.follow)
        self.autostart = _as_bool(self.autostart)

    # --- 写 ---------------------------------------------------------------
    def save(self, path: Path | None = None) -> bool:
        """写失败返回 False 而不是抛异常 —— 存不上配置不该让宠物崩掉。"""
        path = path or config_path()
        payload = {"version": CONFIG_VERSION, **asdict(self)}
        tmp: Path | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # 临时文件必须和目标**同一个目录**: os.replace 只在同一文件系统上原子
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=path.parent, prefix=".config-", suffix=".tmp", delete=False
            ) as fh:
                tmp = Path(fh.name)
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            return True
        except OSError:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
            return False


def _opt_int(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clamp_int(value, lo: int, hi: int, fallback: int) -> int:
    n = _opt_int(value)
    if n is None:
        return fallback
    return lo if n < lo else hi if n > hi else n


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False
