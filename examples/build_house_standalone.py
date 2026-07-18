"""Build and save the realistic house from mayapy standalone."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--assets",
        required=True,
        help="JSON role mapping or {materials, environment} AssetDescriptor bundle",
    )
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--environment", help="Optional JSON AssetDescriptor for an Arnold HDR skydome")
    parser.add_argument("--environment-rotation", type=float, default=0.0)
    parser.add_argument("--environment-exposure", type=float, default=0.0)
    parser.add_argument("--seed", type=int)
    parser.add_argument(
        "--style",
        choices=("craftsman", "farmhouse", "cottage", "tudor", "coastal", "modern_farmhouse"),
        default="craftsman",
    )
    parser.add_argument("--look", choices=("realistic", "stylized"), default="realistic")
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

    asset_bundle = json.loads(Path(args.assets).read_text(encoding="utf-8"))
    material_assets = asset_bundle.get("materials", asset_bundle)
    environment_asset = (
        json.loads(Path(args.environment).read_text(encoding="utf-8"))
        if args.environment
        else asset_bundle.get("environment")
    )

    def report_progress(value: int, message: str) -> None:
        print(f"[{value:3d}%] {message}", flush=True)

    result = generate_house(
        cmds,
        material_assets=material_assets,
        workspace_dir=str(Path(args.workspace).expanduser().resolve()),
        seed=args.seed,
        style=args.style,
        look=args.look,
        frame_count=args.frames,
        environment_asset=environment_asset,
        environment_rotation=args.environment_rotation,
        environment_exposure=args.environment_exposure,
        progress=report_progress,
    )
    cmds.file(rename=str(output))
    cmds.file(save=True, type="mayaAscii", force=True)
    print(json.dumps({"scene": str(output), "result": result}, indent=2))
    cmds.file(new=True, force=True)
    maya.standalone.uninitialize()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)  # Avoid Python finalization after Maya has explicitly released Bifrost and Arnold.


if __name__ == "__main__":
    raise SystemExit(main())
