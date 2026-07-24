# KSI-Terra Reference Policy

## 소유 영역

### KSI-Terra에서 채택할 소유권

- Site spatial truth
- Survey/Spatial Capture
- Raw capture manifest
- Spatial Artifact
- CRS/vertical datum
- Accuracy/GCP
- Static and semi-static Scene Graph
- Orthophoto/DSM/DTM/Point Cloud/Mesh
- Temporal change and quantity
- Processing orchestration

### KSI Edge가 소유할 영역

- Frame-time sensor fusion
- Live perception and tracking
- Dynamic world entities
- Equipment pose and kinematics
- Risk field
- Active perception
- Local path/viewpoint planning
- Flight supervision
- Offline event buffering

## 데이터 흐름

```text
Mission Contract
  → Edge capture/perception
  → Capture Dataset + Event Bundle
  → KSI Core
  → KSI Processing(Terra-derived)
  → MapVersion + Spatial Artifacts
  → Edge Map Compiler
  → next Mission
```

## 제품 통합

별도 Terra 제품 셸을 노출하지 않는다.

KSI Dashboard에서 다음 화면으로 제공한다.

- Site Twin
- Captures
- Progress
- Quantities
- Map Quality
- Exports
- Spatial AI
