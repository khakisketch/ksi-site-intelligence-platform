# Manifold Edge and DJI-native code

This directory contains native Manifold acquisition/runtime composition, diagnostics, platform build
support, and pinned vendor provenance. It does not own DJI Flight Controller behavior.

| Path | Human responsibility | Product status |
|---|---|---|
| `psdk-app/` | Sole production `ksi_psdk_app` composition | Runtime; capabilities remain separately gated |
| `manifold-runtime/` | Reusable local perception/risk/store-forward/control-plane library | Linked by approved native builds |
| `psdk-tap/` | Raw Liveview/telemetry HIL capture probe | Diagnostic only, never product support evidence |
| `msdk-field-bridge/` | Pre/postflight bridge contract candidate | Not verified; no flight actions |
| `psdk-platform/` | Shared PSDK platform/CMake integration | Build support |
| `third_party/` | Pinned vendor provenance and ignored fetched SDK | Read-only build input |
| `docker/` | Manifold cross-build images | Build support |

PSDK Liveview stays local to acquisition/perception. `EDGE_UPLINK` is bounded metadata, and original
media uses its separately documented current or gated target path.
