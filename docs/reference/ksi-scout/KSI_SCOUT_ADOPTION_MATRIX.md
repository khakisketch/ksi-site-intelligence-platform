# KSI-Scout Adoption Matrix

| Scout 자산 | 상태 | KSI 목표 |
|---|---|---|
| NormalizedFrame | PORT | Edge Sensor Frame |
| NormalizedTelemetry | PORT | Edge Aircraft State |
| Capability | EXTRACT | Device Capability/Readiness |
| DroneAdapter | REFERENCE_ONLY | Sensor Adapter interface |
| DJIAdapter MQTT/RTMP | REFERENCE_ONLY | Cloud diagnostic path |
| TelemetryInterpolator | PORT | Edge Sensor Synchronizer |
| Detector ABC | ADOPT | Pluggable Edge detector |
| IoU fallback tracker | REFERENCE_ONLY | Tracker baseline |
| PPE state/size gate | ADOPT | PPE observation policy |
| TemporalVoter | PORT | Time/confidence voter |
| LiveGeoProjector | PORT | Geo Core Golden baseline |
| ZoneLayer | EXTRACT | Static policy zones |
| TrackSpeedEstimator | REFERENCE_ONLY | State-estimation baseline |
| Equipment buffer circles | REPLACE | Kinematic Risk Field |
| EventCandidate | ADOPT | Candidate contract |
| EventEngine | PORT | Persistent Edge event engine |
| EvidenceBuilder | EXTRACT | Signed Event Bundle |
| RuleEngine | ADOPT | Policy evaluation |
| Auth/RBAC/org/site | EXTRACT | KSI Core |
| Audit/Idempotency | ADOPT | KSI Core standard |
| Notifications/reports | EXTRACT | KSI workflow |
| MissionState | REFERENCE_ONLY | Mission execution states |
| WPML builder | SPIKE_REQUIRED | DJI high-level route adapter |
| WeatherGate | EXTRACT | Mission policy gate |
| Mission scheduler | REPLACE | Contract + Edge executive |
| Scout DB jobs | REPLACE | Core/Edge job model |
| Dataset Registry | EXTRACT | Dataset License Ledger |
| Ultralytics training | BLOCKED_LICENSE | Enterprise or replacement |
| RF-DETR | SPIKE_REQUIRED | Permissive detector candidate |
| Scout web | EXTRACT | Event/Evidence UX components |
| Local verify only | REPLACE | CI + HIL |
