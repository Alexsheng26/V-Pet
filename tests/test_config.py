"""配置持久化的测试。不需要 Qt，也不碰真实的配置文件。

    python -m unittest discover
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from vpet.config import DEFAULT_SIZE, MAX_SIZE, MIN_SIZE, Config


class ConfigCase(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.path = Path(self._dir.name) / "nested" / "config.json"

    def tearDown(self) -> None:
        self._dir.cleanup()

    def write(self, text: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(text, encoding="utf-8")


class TestRoundTrip(ConfigCase):
    def test_saves_and_loads(self):
        cfg = Config(x=120, y=340, size=176, follow=True, autostart=True)
        self.assertTrue(cfg.save(self.path))
        self.assertEqual(Config.load(self.path), cfg)

    def test_creates_missing_directories(self):
        self.assertFalse(self.path.parent.exists())
        self.assertTrue(Config().save(self.path))
        self.assertTrue(self.path.is_file())

    def test_leaves_no_temp_files_behind(self):
        Config(x=1, y=2).save(self.path)
        Config(x=3, y=4).save(self.path)
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["config.json"])

    def test_records_a_version(self):
        Config().save(self.path)
        self.assertIn("version", json.loads(self.path.read_text(encoding="utf-8")))


class TestToleratesGarbage(ConfigCase):
    """配置文件坏了不该让宠物起不来 —— 它连报错窗口都没有，用户只会觉得点了没反应。"""

    def test_missing_file_gives_defaults(self):
        self.assertEqual(Config.load(self.path), Config())

    def test_truncated_json_gives_defaults(self):
        self.write('{"x": 10, "y":')          # 模拟写到一半断电
        self.assertEqual(Config.load(self.path), Config())

    def test_json_that_is_not_an_object_gives_defaults(self):
        self.write("[1, 2, 3]")
        self.assertEqual(Config.load(self.path), Config())

    def test_empty_file_gives_defaults(self):
        self.write("")
        self.assertEqual(Config.load(self.path), Config())

    def test_directory_in_place_of_file_gives_defaults(self):
        self.path.mkdir(parents=True)
        self.assertEqual(Config.load(self.path), Config())

    def test_save_failure_returns_false_instead_of_raising(self):
        # 把父目录的位置占成一个文件，mkdir 必然失败
        blocker = Path(self._dir.name) / "nested"
        blocker.write_text("not a directory", encoding="utf-8")
        self.assertFalse(Config().save(self.path))


class TestSchemaCompat(ConfigCase):
    def test_missing_fields_fall_back_to_defaults(self):
        """旧版本写的配置要能被新版本读。"""
        self.write('{"x": 50}')
        cfg = Config.load(self.path)
        self.assertEqual(cfg.x, 50)
        self.assertIsNone(cfg.y)
        self.assertEqual(cfg.size, DEFAULT_SIZE)
        self.assertFalse(cfg.follow)

    def test_unknown_fields_are_ignored(self):
        """新版本写的配置回退到旧版本也要能读。"""
        self.write('{"x": 50, "some_future_option": {"deep": [1]}}')
        self.assertEqual(Config.load(self.path).x, 50)


class TestNormalisation(ConfigCase):
    def test_size_is_clamped(self):
        self.write(f'{{"size": {MAX_SIZE + 999}}}')
        self.assertEqual(Config.load(self.path).size, MAX_SIZE)
        self.write('{"size": 1}')
        self.assertEqual(Config.load(self.path).size, MIN_SIZE)

    def test_nonsense_size_falls_back(self):
        self.write('{"size": "huge"}')
        self.assertEqual(Config.load(self.path).size, DEFAULT_SIZE)

    def test_coordinates_survive_being_strings(self):
        self.write('{"x": "120", "y": "340"}')
        cfg = Config.load(self.path)
        self.assertEqual((cfg.x, cfg.y), (120, 340))

    def test_nonsense_coordinates_become_none(self):
        # None 表示"没存过"，会走默认位置；留着 NaN 之类的会把窗口 move 到鬼地方
        self.write('{"x": "left", "y": null}')
        cfg = Config.load(self.path)
        self.assertIsNone(cfg.x)
        self.assertIsNone(cfg.y)

    def test_truthy_strings_become_booleans(self):
        self.write('{"follow": "true", "autostart": "no"}')
        cfg = Config.load(self.path)
        self.assertIs(cfg.follow, True)
        self.assertIs(cfg.autostart, False)

    def test_booleans_are_not_mistaken_for_coordinates(self):
        # bool 是 int 的子类，int(True) == 1；不特判的话 x 会变成 1
        self.write('{"x": true}')
        self.assertIsNone(Config.load(self.path).x)


if __name__ == "__main__":
    unittest.main()
