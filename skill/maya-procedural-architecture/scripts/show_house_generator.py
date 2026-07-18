"""Open the interactive Maya procedural-house dialog."""

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


show_generator_dialog = _load_architecture().show_generator_dialog


@skill_entry
def main(
    material_assets: Dict[str, Dict[str, Any]],
    workspace_dir: str,
    name: str = "RealisticHouse",
    seed: Optional[int] = None,
    style: str = "craftsman",
    look: str = "realistic",
    environment_asset: Optional[Dict[str, Any]] = None,
    environment_rotation: float = 0.0,
    environment_exposure: float = 0.0,
    **_: Any,
) -> Dict[str, Any]:
    """Show the Qt dialog in interactive Maya."""
    try:
        result = show_generator_dialog(
            material_assets,
            workspace_dir,
            name=name,
            seed=seed,
            style=style,
            look=look,
            environment_asset=environment_asset,
            environment_rotation=environment_rotation,
            environment_exposure=environment_exposure,
        )
        return skill_success("Opened realistic house generator", **result)
    except Exception as exc:
        return skill_exception(exc, message="Failed to open procedural house generator")


if __name__ == "__main__":
    run_main(main)
