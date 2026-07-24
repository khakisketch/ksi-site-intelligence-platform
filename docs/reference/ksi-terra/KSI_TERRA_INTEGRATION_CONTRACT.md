# KSI-Terra Integration Contract

## 1. Site

```json
{
  "siteId": "uuid",
  "orgId": "uuid",
  "name": "string",
  "horizontalCrs": "EPSG:5186",
  "verticalDatum": "KNGeoid2018",
  "sovereign": true
}
```

## 2. Spatial Capture

```json
{
  "captureId": "uuid",
  "siteId": "uuid",
  "missionId": "uuid",
  "capturedAt": "date-time",
  "captureProfile": "BASELINE_MAPPING",
  "status": "QUEUED",
  "source": "EDGE_MANAGED",
  "imageManifestUri": "s3://..."
}
```

## 3. Spatial Artifact

```json
{
  "artifactId": "uuid",
  "captureId": "uuid",
  "kind": "ORTHO_COG",
  "storageUri": "s3://...",
  "crs": "EPSG:5186",
  "verticalDatum": "KNGeoid2018",
  "qualityReportId": "uuid",
  "engine": {
    "name": "ODM",
    "version": "pinned"
  },
  "inputManifestHash": "sha256"
}
```

## 4. Map Version

```json
{
  "mapVersionId": "uuid",
  "siteId": "uuid",
  "derivedFromCaptureIds": ["uuid"],
  "createdAt": "date-time",
  "coverage": {
    "observed": 0.0,
    "reconstructionReady": 0.0,
    "occluded": 0.0,
    "unreachable": 0.0
  },
  "freshness": {
    "score": 0.0,
    "staleTileCount": 0
  }
}
```

## 5. Edge Map Package

```json
{
  "packageId": "uuid",
  "mapVersionId": "uuid",
  "terrainUri": "s3://...",
  "occupancyUri": "s3://...",
  "distanceFieldUri": "s3://...",
  "semanticSurfaceUri": "s3://...",
  "policyVolumesUri": "s3://...",
  "signature": "..."
}
```

## 규칙

- Artifact는 Capture 없이 존재할 수 없다.
- Capture는 Mission 또는 명시적 BYO Import를 가져야 한다.
- 다른 CRS MapVersion을 자동 병합하지 않는다.
- Edge는 원본 고밀도 모델이 아니라 서명된 Edge Map Package를 사용한다.
- 미검증 품질 수치를 절대정확도로 표시하지 않는다.
