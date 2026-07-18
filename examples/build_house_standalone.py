"""Build and save the realistic house from mayapy standalone."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", required=True, help="JSON role-to-AssetDescriptor mapping")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--style", choices=("craftsman", "farmhouse", "cottage"), default="craftsman")
    parser.add_argument("--frames", type=int, default=96)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    scripts = Path(__file__).resolve().parents[1] / "skill" / "maya-procedural-architecture" / "scripts"
    sys.path.insert(0, str(scripts))

    import maya.standalone

    maya.standalone.initialize(name="python")
    import maya.cmds as cmds
    from _architecture import generate_house

    material_assets = json.loads(Path(args.assets).read_text(encoding="utf-8"))
    result = generate_house(
        cmds,
        material_assets=material_assets,
        workspace_dir=str(Path(args.workspace).expanduser().resolve()),
        seed=args.seed,
        style=args.style,
        frame_count=args.frames,
    )
    cmds.file(rename=str(output))
    cmds.file(save=True, type="mayaAscii", force=True)
    print(json.dumps({"scene": str(output), "result": result}, indent=2))
    sys.stdout.flush()
    sys.stderr.flush()
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.TerminateProcess(kernel32.GetCurrentProcess(), 0)
    os._exit(0)  # Avoid Maya Bifrost/Arnold shutdown callbacks after the scene is safely written.


if __name__ == "__main__":
    raise SystemExit(main())
