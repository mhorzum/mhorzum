"""ClickConfig dogrulama ve nokta secimi testleri (tkinter gerektirmez)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autoclicker.clicker import ClickConfig, ClickWorker  # noqa: E402


class TestClickConfig(unittest.TestCase):
    def test_default_region_is_invalid(self):
        self.assertIn("Gecerli bir tiklama alani secilmedi.", ClickConfig().validate())

    def test_valid_config_has_no_errors(self):
        cfg = ClickConfig(region=(100, 100, 400, 300), total_clicks=5)
        self.assertEqual(cfg.validate(), [])

    def test_max_must_not_be_below_min(self):
        cfg = ClickConfig(region=(0, 0, 10, 10), min_interval=90, max_interval=10)
        self.assertTrue(any("en kisa sureden" in e for e in cfg.validate()))

    def test_unlimited_clicks_allowed(self):
        cfg = ClickConfig(region=(0, 0, 10, 10), total_clicks=0)
        self.assertEqual(cfg.validate(), [])

    def test_roundtrip_serialisation(self):
        cfg = ClickConfig(region=(1, 2, 3, 4), total_clicks=7, min_interval=1.5)
        restored = ClickConfig.from_dict(cfg.to_dict())
        self.assertEqual(restored, cfg)

    def test_from_dict_ignores_unknown_and_broken_fields(self):
        cfg = ClickConfig.from_dict({"region": "bozuk", "surprise": 1, "total_clicks": 3})
        self.assertEqual(cfg.total_clicks, 3)
        self.assertEqual(cfg.region, (0, 0, 0, 0))


class TestPointSelection(unittest.TestCase):
    def test_random_point_stays_inside_region(self):
        cfg = ClickConfig(region=(100, 200, 140, 260), random_point=True)
        worker = ClickWorker(cfg, lambda *a, **k: None)
        for _ in range(200):
            x, y = worker._pick_point()
            self.assertTrue(100 <= x < 140, x)
            self.assertTrue(200 <= y < 260, y)

    def test_center_point(self):
        cfg = ClickConfig(region=(100, 200, 140, 260), random_point=False)
        worker = ClickWorker(cfg, lambda *a, **k: None)
        self.assertEqual(worker._pick_point(), (120, 230))


if __name__ == "__main__":
    unittest.main()
