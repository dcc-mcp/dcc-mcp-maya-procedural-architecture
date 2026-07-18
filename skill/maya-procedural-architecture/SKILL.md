---
name: maya-procedural-architecture
description: >-
  Generate detailed, seed-driven residential architecture in Maya with typed
  Bifrost structural graphs, instanced finish meshes, realistic or stylized
  Arnold materials, and optional CC0 HDR lighting. Use for exterior house
  generation, GUI iteration, and standalone mayapy scene builds. Not for
  generic graph editing or asset downloads.
license: MIT
compatibility: "Maya 2022+; Python 3.7+; dcc-mcp-core 0.19+"
allowed-tools: Bash Read
metadata:
  dcc-mcp:
    dcc: maya
    version: "1.0.1" # x-release-please-version
    layer: domain
    stage: authoring
    tags: ["maya", "bifrost", "architecture", "procedural-modeling", "arnold", "pbr", "hdri", "stylized"]
    search-hint: "realistic stylized procedural house, detailed home generator, Bifrost architecture, Arnold PBR HDR house, craftsman farmhouse cottage Tudor coastal, house generator GUI"
    tools: tools.yaml
    depends:
      - maya-bifrost
      - maya-materials
      - maya-render
      - ambientcg-assets
---

# Maya Procedural Architecture

Use `ambientcg-assets` first to download four PBR materials and an optional HDRI. Pass the
returned `AssetDescriptor` objects by role: `siding`, `roof`, `brick`, and
`concrete`. The generator safely extracts their texture maps, writes a CC0
attribution manifest, and connects color, roughness, OpenGL normal, AO, and
height maps to Arnold `standardSurface` materials through object-space
triplanar projection. An HDR descriptor drives the Arnold SkyDome; an Arnold
Area light provides a controllable key.

## Recommended flow

1. Search and download suitable CC0 materials and, optionally, an HDRI with
   `ambientcg-assets`.
2. Call `generate_realistic_house` with the four descriptors and an absolute
   workspace directory. Reuse its seed for an identical result.
3. Use the returned camera with `maya-render` for an Arnold beauty render or
   the returned orbit frame range for a turntable.
4. In interactive Maya, call `show_house_generator` with the same descriptors
   to open the seed/style/look GUI. It exposes cancellable progress while the
   sidecar continues to dispatch Maya work on its QTimer-backed main-thread
   queue.

The generator supports `craftsman`, `farmhouse`, `cottage`, `tudor`, `coastal`,
and `modern_farmhouse` presets. Architecture style and material look are
orthogonal: use `look=realistic` for physically based response or
`look=stylized` for brighter color, softer normals, and simplified highlights.
Generic graph authoring remains in `maya-bifrost`; CC0 download logic remains
in the asset provider.
