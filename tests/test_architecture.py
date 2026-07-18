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

from _architecture import (  # noqa: E402
    MATERIAL_ORDER,
    MAX_GENERATED_PARTS,
    SUPPORTED_LOOKS,
    SUPPORTED_STYLES,
    TEXTURE_ROLES,
    _emit_progress,
    _maya_generation_guard,
    _select_render_camera,
    design_house,
    prepare_textures,
)


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
    designs = {style: design_house(seed=20260718, style=style) for style in SUPPORTED_STYLES}

    assert {design.style for design in designs.values()} == set(designs)
    assert len({design.parts for design in designs.values()}) == len(SUPPORTED_STYLES) == 6
    with pytest.raises(ValueError, match="modern_farmhouse"):
        design_house(seed=1, style="modern")


def test_seeded_variation_is_rich_but_bounded() -> None:
    designs = [design_house(seed=seed, style=SUPPORTED_STYLES[seed % len(SUPPORTED_STYLES)]) for seed in range(30)]

    assert all(150 <= len(design.parts) <= MAX_GENERATED_PARTS for design in designs)
    assert {feature for design in designs for feature in design.features} >= {"garage_left", "garage_right"}
    assert len({design.features for design in designs}) >= 12
    assert max(len(design.parts) for design in designs) - min(len(design.parts) for design in designs) >= 20


def test_progress_values_are_clamped() -> None:
    events = []
    _emit_progress(lambda value, message: events.append((value, message)), -4, "start")
    _emit_progress(lambda value, message: events.append((value, message)), 108, "done")
    assert events == [(0, "start"), (100, "done")]


def test_maya_generation_guard_restores_host_state_after_failure() -> None:
    class FakeCmds:
        def __init__(self) -> None:
            self.calls = []

        def undoInfo(self, **kwargs):
            self.calls.append(("undo", kwargs))
            if kwargs.get("query"):
                return True
            return None

        def autoKeyframe(self, **kwargs):
            self.calls.append(("autokey", kwargs))
            if kwargs.get("query"):
                return True
            return None

        def refresh(self, **kwargs):
            self.calls.append(("refresh", kwargs))

    cmds = FakeCmds()
    with pytest.raises(RuntimeError, match="probe"), _maya_generation_guard(cmds):
        raise RuntimeError("probe")

    assert cmds.calls[-3:] == [
        ("autokey", {"state": True}),
        ("undo", {"stateWithoutFlush": True}),
        ("refresh", {"suspend": False}),
    ]


def test_gui_uses_qtimer_and_cancellable_progress() -> None:
    source = (SCRIPTS / "_architecture.py").read_text(encoding="utf-8")
    assert "QtCore.QTimer.singleShot(0, self._run_generation)" in source
    assert "QtWidgets.QProgressDialog" in source
    assert "GenerationCancelled" in source


def _descriptor(tmp_path: Path, role: str) -> dict:
    archive = tmp_path / (role + ".zip")
    with zipfile.ZipFile(archive, "w") as bundle:
        for suffix in ("Color", "Roughness", "NormalGL", "AmbientOcclusion", "Displacement"):
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
    assert set(result["materials"]["siding"]["maps"]) == {
        "color",
        "roughness",
        "normal",
        "ao",
        "displacement",
    }


def test_prepare_textures_accepts_cc0_hdr_environment(tmp_path: Path) -> None:
    assets = {role: _descriptor(tmp_path, role) for role in TEXTURE_ROLES}
    archive = tmp_path / "day-sky.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("DaySkyHDRI001A_2K.exr", b"linear-hdr")
    environment = {
        "asset_id": "ambientcg:DaySkyHDRI001A",
        "variants": [{"local_path": str(archive), "format": "zip", "preferred": True}],
        "attribution": {
            "source_url": "https://ambientcg.com/a/DaySkyHDRI001A",
            "license_spdx": "CC0-1.0",
        },
    }

    result = prepare_textures(assets, str(tmp_path / "workspace"), environment)

    assert Path(result["environment"]["path"]).suffix == ".exr"
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["environment"]["asset_id"] == "ambientcg:DaySkyHDRI001A"


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
    assert all(tool["input_schema"]["properties"]["look"]["enum"] == list(SUPPORTED_LOOKS) for tool in tools)
    assert all("environment_asset" in tool["input_schema"]["properties"] for tool in tools)


def test_realistic_material_path_uses_ao_and_micro_bump() -> None:
    source = (SCRIPTS / "_architecture.py").read_text(encoding="utf-8")
    assert 'cmds.shadingNode("aiBump2d"' in source
    assert 'name + "_ColorAO"' in source
    assert '"enableAdaptiveSampling", realistic' in source
    assert 'cmds.shadingNode("aiSkyDomeLight"' in source
    assert 'cmds.shadingNode("aiAreaLight"' in source
    assert 'name=base + "_EnvironmentHDR"' in source
    assert 'base + "_EnvironmentHDR"' in source[source.index("def _cleanup_generated_nodes") :]


def test_staged_camera_is_the_only_batch_render_camera() -> None:
    class FakeCmds:
        def __init__(self) -> None:
            self.values = {}

        def ls(self, *, type: str):
            assert type == "camera"
            return ["perspShape", "houseRenderShape"]

        def setAttr(self, attribute: str, value: bool) -> None:
            self.values[attribute] = value

    cmds = FakeCmds()
    _select_render_camera(cmds, "houseRenderShape")

    assert cmds.values == {
        "perspShape.renderable": False,
        "houseRenderShape.renderable": True,
    }


def test_skill_entrypoints_load_without_scripts_on_sys_path(monkeypatch) -> None:
    monkeypatch.setattr(sys, "path", [item for item in sys.path if Path(item).resolve() != SCRIPTS])
    for filename in ("generate_realistic_house.py", "show_house_generator.py"):
        path = SCRIPTS / filename
        spec = importlib.util.spec_from_file_location("_entry_" + path.stem, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
