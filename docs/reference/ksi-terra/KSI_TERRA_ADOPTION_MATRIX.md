# KSI-Terra Adoption Matrix

| KSI-Terra 자산 | 상태 | KSI 활용 |
|---|---|---|
| Organization/Project | EXTRACT | Organization/Site 계약 |
| Survey | ADOPT | Spatial Capture anchor |
| RawImageSet | ADOPT | Capture Dataset |
| Artifact | ADOPT | Spatial Artifact/Map Layer |
| AccuracyReport | ADOPT | Spatial Quality |
| GcpPoint/ImageMark | ADOPT | GCP/CP workflow |
| Zone | EXTRACT | Semantic Zone + 3D Policy Volume |
| SceneObject | EXTRACT | Static/Semi-static World Entity |
| Relationship | EXTRACT | Scene Graph relation |
| JobRunner | ADOPT | Processing Engine Adapter |
| ComputeTarget | ADOPT | Processing Node routing |
| JobQueue | ADOPT | PostgreSQL job leasing |
| JobWorker | ADOPT | retry/resume/dead-letter |
| ODMRunner | ADOPT | default OSS photogrammetry adapter |
| MetashapeRunner | REFERENCE_ONLY | benchmark/optional licensed adapter |
| PlaceholderRunner | REMOVE_PROD | test only |
| COG pipeline | ADOPT | 2D spatial raster |
| DSM/DTM | ADOPT | terrain/surface/map freshness |
| COPC | ADOPT | point cloud streaming |
| 3D Tiles single tile | REPLACE | hierarchical LOD |
| DJI XMP parser | ADOPT_AFTER_SPIKE | real M4D validation |
| DSM diff/volume | ADOPT | progress/earthwork |
| Grounding DINO | REFERENCE_ONLY | offline detection/bootstrap |
| Scene detection API | EXTRACT | post-flight spatial AI |
| SceneObject identity | REPLACE | probabilistic multi-feature identity |
| Natural-language query | ADOPT_LIMITED | post-flight analytics only |
| S3 ObjectStore | ADOPT | MinIO/S3 data plane |
| Multipart/checksum | ADOPT | large media ingestion |
| JWT/RLS patterns | ADOPT | Core security |
| Audit/tracing/metrics | ADOPT | platform operations |
| Next.js Terra UI | EXTRACT | KSI Dashboard components |
| Demo mock fallback | REMOVE_PROD | explicit dev fixture only |
| Order/Billing/Support | DEFER | later commercial ops |
| cadastral/public procurement | DEFER | later market expansion |
| no-direct-control ADR | SUPERSEDED | Edge mission autonomy required |
