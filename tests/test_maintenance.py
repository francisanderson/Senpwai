"""Deterministic checks for the offline/live maintenance boundary."""
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MaintenanceConfigurationTests(unittest.TestCase):
    def test_offline_task_is_explicit_and_live_smokes_remain_separate(self):
        config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        tasks = config["tool"]["poe"]["tasks"]

        self.assertEqual(
            tasks["test_offline"],
            "python -m unittest discover -s tests -v",
        )
        self.assertIn("senpwai.scrapers.test", tasks["test_pahe_dpl"])
        self.assertIn("senpwai.scrapers.test", tasks["test_gogo_norm"])

    def test_workflow_runs_offline_checks_before_live_smoke(self):
        workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(
            encoding="utf-8"
        )
        offline = workflow.index("poetry run poe test_offline")
        live = workflow.index("poetry run poe test_pahe_dpl")
        self.assertLess(offline, live)
        self.assertLess(offline, workflow.index("live-smoke:"))
        self.assertIn("needs: offline", workflow)
        self.assertNotIn("continue-on-error: true", workflow)
        self.assertIn("libegl1", workflow)
        self.assertIn("libgl1", workflow)
        self.assertIn("libxkbcommon0", workflow)


if __name__ == "__main__":
    unittest.main()
