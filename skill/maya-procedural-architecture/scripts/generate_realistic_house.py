"""Generate a detailed, textured Bifrost house in Maya."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from dcc_mcp_core.skill import run_main, skill_entry, skill_exception, skill_success


def _load_architecture():
    module_name = "dcc_skill_maya_procedural_architecture_runtime"
    module = sys.modules.get(module_name)
    if module is not None:
        return module
    path = Path(__file__).with_name("_architecture.py")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load architecture runtime: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


generate_house = _load_architecture().generate_house


@skill_entry
def main(
    material_assets: Dict[str, Dict[str, Any]],
    workspace_dir: str,
    seed: Optional[int] = None,
    style: str = "craftsman",
    name: str = "RealisticHouse",
    replace: bool = True,
    frame_count: int = 96,
    **_: Any,
) -> Dict[str, Any]:
    """Build the house on Maya's main thread and return render-ready context."""
    try:
        import maya.cmds as cmds  # noqa: PLC0415

        result = generate_house(
            cmds,
            material_assets=material_assets,
            workspace_dir=workspace_dir,
            seed=seed,
            style=style,
            name=name,
            replace=replace,
            frame_count=frame_count,
        )
        return skill_success(
            "Generated detailed Bifrost house with Arnold PBR materials",
            prompt="Render the returned camera with maya-render or inspect the orbit frame range.",
            **result,
        )
    except Exception as exc:
        return skill_exception(exc, message="Failed to generate realistic procedural house")


if __name__ == "__main__":
    run_main(main)
