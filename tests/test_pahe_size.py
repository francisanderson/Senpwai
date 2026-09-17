"""Offline checks of the production parser without legacy import side effects."""
import ast
from pathlib import Path
import re
from typing import cast
import unittest


# Importing the scraper normally reaches legacy installer deletion code.
# Compile the actual production function and regex, not copies of their logic.
PAHE = Path(__file__).resolve().parents[1] / "senpwai" / "scrapers" / "pahe"
namespace = {"re": re, "cast": cast}
for filename, name in (
    ("constants.py", "EPISODE_SIZE_REGEX"),
    ("main.py", "calculate_total_download_size"),
):
    tree = ast.parse((PAHE / filename).read_text(encoding="utf-8"))
    node = next(
        node for node in tree.body
        if (isinstance(node, ast.FunctionDef) and node.name == name)
        or (isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ))
    )
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(PAHE / filename), "exec"), namespace)
calculate_total_download_size = namespace["calculate_total_download_size"]


class DownloadSizeTests(unittest.TestCase):
    def test_missing_metadata_is_explicit(self):
        for labels in (["Unknown"], ["100MB", "Unknown"]):
            with self.subTest(labels=labels):
                with self.assertRaisesRegex(ValueError, "missing size metadata"):
                    calculate_total_download_size(labels)

    def test_valid_sizes_and_empty_list_are_unchanged(self):
        self.assertEqual(calculate_total_download_size(["720p 100MB", "1080p 250MB"]), 350)
        self.assertEqual(calculate_total_download_size([]), 0)


if __name__ == "__main__":
    unittest.main()
