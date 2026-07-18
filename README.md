# dcc-mcp-maya-procedural-architecture

High-detail residential architecture for Maya. The skill builds seeded
craftsman, farmhouse, and cottage exteriors with material-separated Bifrost
structural graphs and beveled Maya finish details, applies real CC0 PBR
textures with Arnold triplanar shading, and stages a render camera and orbit.

![Seeded Maya and Bifrost procedural house styles](docs/showcase/maya-bifrost-random-houses.gif)

The showcase is a 51-frame, 1280×720 Arnold render cycling three deterministic
style presets. The [turntable contact sheet](docs/showcase/turntable-contact-sheet.jpg)
shows four rendered camera angles for every preset.

House-specific code lives here. The Maya adapter keeps only generic typed
Bifrost/VNN graph operations, while `dcc-asset-ambientcg` owns asset discovery
and downloads.

## Tools

- `generate_realistic_house` — works through an interactive Maya sidecar and
  in `mayapy` standalone.
- `show_house_generator` — opens a Maya Qt dialog with seed and randomize
  controls; host work remains on the sidecar's QTimer main-thread path.

## PBR asset flow

Use the marketplace `ambientcg-assets` skill to search and download four CC0
materials. Pass its returned `AssetDescriptor` objects by role:

```json
{
  "material_assets": {
    "siding": {"asset_id": "ambientcg:WoodSiding008", "variants": [], "attribution": {}},
    "roof": {"asset_id": "ambientcg:RoofingTiles013A", "variants": [], "attribution": {}},
    "brick": {"asset_id": "ambientcg:Bricks060", "variants": [], "attribution": {}},
    "concrete": {"asset_id": "ambientcg:Concrete034", "variants": [], "attribution": {}}
  },
  "workspace_dir": "C:/absolute/house-workspace",
  "seed": 20260718
}
```

The abbreviated objects above show routing only; pass the complete descriptors
returned by the provider. The generator extracts color, roughness, and OpenGL
normal maps and writes `asset_attribution.json` beside the textures.

## Standalone

```powershell
& "C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe" `
  examples\build_house_standalone.py `
  --assets assets.json `
  --workspace C:\house-workspace `
  --output C:\house-workspace\realistic-house.ma `
  --style farmhouse `
  --seed 20260718
```

`assets.json` contains the role-to-AssetDescriptor mapping. In Maya GUI, load
the skill and call `show_house_generator` with the same mapping.

## Development

```powershell
vx ruff check skill tests examples
vx ruff format --check skill tests examples
vx uv run --with pytest --with pyyaml pytest
vx uv run --with "dcc-mcp-core>=0.19" python `
  C:\Users\hallong\.codex\skills\dcc-mcp-skills-creator\scripts\validate_skill_dir.py `
  skill\maya-procedural-architecture
```

## License

Code is MIT licensed. Downloaded material assets are not bundled; each
AssetDescriptor and generated manifest retains the provider's CC0 license and
source URL.
