from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evalgate.pricing import cost_usd, load_pricing, resolve  # noqa: E402

PRICING = load_pricing(ROOT / "pricing.json")


class TestResolve(unittest.TestCase):
    def test_exact_id(self):
        self.assertIsNotNone(resolve(PRICING, "mistral-small-4-0-26-03"))

    def test_alias(self):
        entry = resolve(PRICING, "mistral-small-latest")
        self.assertEqual(entry["input"], 0.15)

    def test_unknown_model(self):
        self.assertIsNone(resolve(PRICING, "some-model-from-2023"))


class TestCost(unittest.TestCase):
    def test_one_million_input_tokens(self):
        self.assertAlmostEqual(cost_usd(PRICING, "mistral-small-4-0-26-03", 1_000_000, 0), 0.15)

    def test_mixed_tokens(self):
        # 2k input at $0.15/M plus 500 output at $0.60/M
        expected = (2000 * 0.15 + 500 * 0.6) / 1_000_000
        self.assertAlmostEqual(cost_usd(PRICING, "mistral-small-4-0-26-03", 2000, 500), expected)

    def test_cached_tokens_are_cheaper(self):
        full = cost_usd(PRICING, "mistral-large-4-0", 1_000_000, 0)
        cached = cost_usd(PRICING, "mistral-large-4-0", 1_000_000, 0, cached_tokens=1_000_000)
        self.assertLess(cached, full)
        self.assertAlmostEqual(cached, 0.07)

    def test_unknown_model_returns_none_not_zero(self):
        self.assertIsNone(cost_usd(PRICING, "unknown-model", 1000, 1000))


if __name__ == "__main__":
    unittest.main()
