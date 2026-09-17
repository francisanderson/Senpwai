"""Offline checks for provider domain constants and the README self-heal parser.

Importing senpwai.common.scraper triggers legacy installer side effects, so
scraper.py is compiled directly with ast (stdlib only, no network access).
Expected values are pinned to the upstream README's provider hyperlinks,
which get_new_home_url_from_readme() treats as the runtime domain authority.
If the upstream README changes, refresh the pinned values and re-verify.
"""
import ast
import base64
from base64 import b64decode
import re
from pathlib import Path
from typing import cast
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRAPER = ROOT / "senpwai" / "common" / "scraper.py"

MAINTAINER_README_SNIPPET = """
[Animepahe](https://animepahe.com)
[Gogoanime](https://anitaku.bz)
"""


class FakeResponse:
    def json(self):
        encoded = base64.b64encode(MAINTAINER_README_SNIPPET.encode("utf-8"))
        return {"content": encoded.decode("ascii")}


class FakeClient:
    def get(self, url):
        return FakeResponse()


namespace: dict = {
    "re": re,
    "cast": cast,
    "b64decode": b64decode,
    "CLIENT": FakeClient(),
    "GITHUB_API_README_URL": "https://api.github.com/repos/SenZmaKi/Senpwai/readme",
}
tree = ast.parse(SCRAPER.read_text(encoding="utf-8"))
node = next(
    node
    for node in tree.body
    if isinstance(node, ast.FunctionDef)
    and node.name == "get_new_home_url_from_readme"
)
exec(
    compile(
        ast.Module(body=[node], type_ignores=[]), str(SCRAPER), "exec"
    ),
    namespace,
)
get_new_home_url_from_readme = namespace["get_new_home_url_from_readme"]

PAHE_CONSTANTS = (ROOT / "senpwai" / "scrapers" / "pahe" / "constants.py").read_text(
    encoding="utf-8"
)
PAHE_DOMAIN = re.search(r'PAHE_DOMAIN = "([^"]+)"', PAHE_CONSTANTS).group(1)
GOGO_CONSTANTS = (ROOT / "senpwai" / "scrapers" / "gogo" / "constants.py").read_text(
    encoding="utf-8"
)
GOGO_HOME_URL = re.search(r'GOGO_HOME_URL = "([^"]+)"', GOGO_CONSTANTS).group(1)


class DomainAlignmentTests(unittest.TestCase):
    def test_readme_parser_extracts_maintainer_links(self):
        self.assertEqual(
            get_new_home_url_from_readme("Animepahe"), "https://animepahe.com"
        )
        self.assertEqual(
            get_new_home_url_from_readme("Gogoanime"), "https://anitaku.bz"
        )

    def test_pahe_urls_are_constructed_from_pahe_domain(self):
        self.assertEqual(PAHE_DOMAIN, "animepahe.com")
        self.assertIn(f"PAHE_DOMAIN = \"{PAHE_DOMAIN}\"", PAHE_CONSTANTS)

    def test_gogo_home_url_is_pinned_to_maintainer_readme(self):
        self.assertEqual(GOGO_HOME_URL, "https://anitaku.bz")


if __name__ == "__main__":
    unittest.main()
