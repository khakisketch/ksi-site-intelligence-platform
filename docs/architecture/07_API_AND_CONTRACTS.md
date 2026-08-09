# API and Contract Design

## Main contracts

- MissionContract
- EdgeStatus
- WorldEntity
- Observation
- RiskField
- EventBundle
- CoverageReport
- ProcessingJob — `contracts/schemas/processing-job.v1.json`
- ProcessingArtifact — `contracts/schemas/processing-artifact.v1.json`
- WorldModelManifest (미구현 — 선언만)
- ModelDeployment (미구현 — 선언만)

## Transport

- Core REST/GraphQL as product API
- MQTT/WebSocket for realtime state
- Protobuf for Edge messages
- Presigned object storage for media
- 3D Tiles/COG streaming for large spatial artifacts

## Reliability

Every Edge upload uses device sequence, idempotency key and checksum. Core acknowledges durable persistence before Edge deletes local data.
