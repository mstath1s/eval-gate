from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evalgate.cli import main  # noqa: E402


class TestCliOffline(unittest.TestCase):
    def test_default_gate_fails_on_the_fixture_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = main(
                [
                    "run",
                    "--suite", str(ROOT / "suites" / "support-triage.json"),
                    "--offline",
                    "--gate", str(ROOT / "gates" / "default.json"),
                    "--out", tmp,
                    "--quiet",
                ]
            )
            self.assertEqual(code, 1)
            report = next(Path(tmp).glob("*.md")).read_text(encoding="utf-8")
            self.assertIn("GATE: FAIL", report)
            self.assertIn("triage-003", report)

    def test_lenient_gate_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            gate = Path(tmp) / "lenient.json"
            gate.write_text(
                '{"min_pass_rate": 0.5, "max_error_rate": 0.0, "max_total_cost_usd": 5.0}',
                encoding="utf-8",
            )
            code = main(
                [
                    "run",
                    "--suite", str(ROOT / "suites" / "support-triage.json"),
                    "--offline",
                    "--gate", str(gate),
                    "--out", tmp,
                    "--quiet",
                ]
            )
            self.assertEqual(code, 0)
            report = next(Path(tmp).glob("*.md")).read_text(encoding="utf-8")
            self.assertIn("GATE: PASS", report)

    def test_missing_offline_fixture_is_a_config_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = main(
                [
                    "run",
                    "--suite", str(ROOT / "suites" / "grounded-answers.json"),
                    "--offline",
                    "--answers", str(Path(tmp) / "nope.json"),
                    "--out", tmp,
                    "--quiet",
                ]
            )
            self.assertEqual(code, 2)

    def test_graders_command_lists_names(self):
        self.assertEqual(main(["graders"]), 0)


if __name__ == "__main__":
    unittest.main()
