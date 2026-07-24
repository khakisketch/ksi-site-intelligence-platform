# KSI-Terra Migration Plan

## Phase 0 — Runtime Truth Audit

- 현재 head CI 실행
- 실제 NodeODM version 확인
- production env의 Runner 확인
- mock fallback 확인
- ObjectStore backend 확인
- schema migration head 확인
- 최신 M4D 사진으로 XMP parser 검증

## Phase 1 — Contract Convergence

- Project↔Site mapping
- Survey↔SpatialCapture
- Artifact↔SpatialArtifact
- Zone↔SemanticZone
- SceneObject↔StaticWorldEntity
- Shared UUID와 s3 URI 사용

## Phase 2 — Processing Adoption

- Terra JobRunner를 KSI Processing Adapter로 등록
- ComputeTarget를 ProcessingNode Capability와 연결
- production placeholder 차단
- ODM GCP/geo 옵션 연결
- Artifact provenance/version/hash 강화

## Phase 3 — Spatial Outputs

- Orthophoto/DSM/DTM/COPC/GLB publish
- hierarchical 3D Tiles
- MapVersion 생성
- Change/volume 자동 실행
- Quality Gate
- Map Freshness

## Phase 4 — Edge Map Compiler

- Terrain map
- Occupancy
- ESDF
- Surface map
- Semantic zones
- Occlusion
- signed package

## Phase 5 — 4D World Model Bridge

- static SceneObject를 Edge seed로 제공
- Edge dynamic entity snapshots 수신
- observation lineage 연결
- post-flight consolidation
- robust identity matching
