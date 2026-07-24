# Scout Data & Model Policy

## 지원 수준

- DATASET_DISCOVERED
- TRAINABLE
- BASELINE_VALIDATED
- FIELD_VALIDATED
- GEO_VALIDATED
- RISK_VALIDATED
- PRODUCTION_SUPPORTED

## 상용 학습 Gate

- 데이터 원본 URL과 Version 고정
- License 전문 또는 Snapshot 보존
- Attribution 생성
- NC 데이터 Commercial training 제외
- Duplicate/Leakage 검사
- Site/date/customer split
- 개인정보·초상권·현장 반출권한
- Synthetic data 표시
- Label provenance

## Model Gate

- Model source
- Code license
- Weight license
- Training dataset manifest
- Export/TensorRT toolchain
- Precision/Recall by site and range
- Calibration/ECE
- Latency/temperature/power
- Signed deployment
- Rollback
