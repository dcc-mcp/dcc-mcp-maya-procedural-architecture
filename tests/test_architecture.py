from __future__ import annotations

import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / "skill" / "maya-procedural-architecture" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from _architecture import MATERIAL_ORDER, TEXTURE_ROLES, design_house, prepare_textures  # noqa: E402


def test_design_is_deterministic_and_detailed() -> None:
    first = design_house(seed=20260718)
    second = design_house(seed=20260718)

    assert first == second
    assert first.style == "craftsman"
    assert len(first.parts) >= 150
    assert set(MATERIAL_ORDER) == {part.material for part in first.parts}
    assert any(part.rotation_z for part in first.parts if part.material == "roof")
    assert len([part for part in first.parts if "window" in part.name]) >= 40


def test_seed_changes_architectural_dimensions() -> None:
    assert design_house(seed=1).parts != design_house(seed=2).parts


def test_styles_produce_distinct_deterministic_architecture() -> None:
    designs = {style: design_house(seed=20260718, style=style) for style in ("craftsman", "farmhouse", "cottage")}

    assert {design.style for design in designs.values()} == set(designs)
    assert len({design.parts for design in designs.values()}) == 3
    with pytest.raises(ValueError, match="craftsman, farmhouse, cottage"):
        design_house(seed=1, style="modern")


def _descriptor(tmp_path: Path, role: str) -> dict:
    archive = tmp_path / (role + ".zip")
    with zipfile.ZipFile(archive, "w") as bundle:
        for suffix in ("Color", "Roughness", "NormalGL"):
            bundle.writestr(f"{role}_2K-JPG_{suffix}.jpg", b"image")
    return {
        "asset_id": f"ambientcg:{role}",
        "variants": [{"local_path": str(archive), "format": "zip", "preferred": True}],
        "attribution": {
            "source_url": f"https://ambientcg.com/a/{role}",
            "license_spdx": "CC0-1.0",
            "attribution_text": "ambientCG asset - CC0 1.0 Universal.",
        },
    }


def test_prepare_textures_consumes_descriptors_and_writes_manifest(tmp_path: Path) -> None:
    assets = {role: _descriptor(tmp_path, role) for role in TEXTURE_ROLES}
    result = prepare_textures(assets, str(tmp_path / "workspace"))

    manifest = Path(result["manifest"])
    assert manifest.is_file()
    assert json.loads(manifest.read_text(encoding="utf-8"))["roof"]["attribution"]["license_spdx"] == "CC0-1.0"
    assert set(result["materials"]["siding"]["maps"]) == {"color", "roughness", "normal"}


def test_prepare_textures_rejects_non_cc0_assets(tmp_path: Path) -> None:
    assets = {role: _descriptor(tmp_path, role) for role in TEXTURE_ROLES}
    assets["roof"]["attribution"]["license_spdx"] = "LicenseRef-Unknown"
    with pytest.raises(ValueError, match="CC0-1.0"):
        prepare_textures(assets, str(tmp_path / "workspace"))


def test_tool_contracts_use_main_affinity() -> None:
    tools_path = SCRIPTS.parent / "tools.yaml"
    tools = yaml.safe_load(tools_path.read_text(encoding="utf-8"))["tools"]
    assert [tool["name"] for tool in tools] == ["generate_realistic_house", "show_house_generator"]
    assert all(tool["affinity"] == "main" for tool in tools)
    assert all(tool["enforce_thread_affinity"] is True for tool in tools)


def test_skill_entrypoints_load_without_scripts_on_sys_path(monkeypatch) -> None:
    monkeypatch.setattr(sys, "path", [item for item in sys.path if Path(item).resolve() != SCRIPTS])
    for filename in ("generate_realistic_house.py", "show_house_generator.py"):
        path = SCRIPTS / filename
        spec = importlib.util.spec_from_file_location("_entry_" + path.stem, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
