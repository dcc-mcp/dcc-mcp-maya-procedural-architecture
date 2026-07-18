import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_marketplace_showcase_is_installable_from_an_immutable_revision():
    entry = json.loads((ROOT / "marketplace.json").read_text(encoding="utf-8"))["entries"][0]
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project_version = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE)

    assert project_version is not None
    assert entry["version"] == project_version.group(1)
    assert re.fullmatch(r"[0-9a-f]{40}", entry["install"]["ref"])
    assert (ROOT / entry["showcase"]).is_file()
    assert Path(entry["showcase"]).suffix.lower() == ".gif"
    assert entry["install"]["skillRoots"] == ["skill/maya-procedural-architecture"]
    assert "ambientcg-assets" in entry["requires"]["skills"]
