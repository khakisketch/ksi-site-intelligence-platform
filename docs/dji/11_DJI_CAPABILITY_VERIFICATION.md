# DJI Capability Verification Matrix

## 2026-08-27 real-device observation

RC Plus 2/Pilot 2 loaded the KSI read-only Open Platform probe in a propeller-removed,
no-flight/no-motor session. The operator observed `window.djiBridge` and the six inspected bootstrap
method names as present: `platformGetVersion`, `platformIsVerified`, `platformVerifyLicense`,
`platformLoadComponent`, `platformIsComponentLoaded` and `apiGetToken`.

The probe called no bridge function, read no identifier or token, and transmitted no result. The
evidence class is `OPERATOR_ATTESTED_LIVE_OBSERVATION`; raw screen evidence was not captured. The
accepted verdict is only `JSBRIDGE_SURFACE_OBSERVED`. License authentication, component loading,
Wayline/Media/MQTT/WS/MOP behavior and the exact M4D + RC Plus 2 combination remain
`NOT_VERIFIED`; every production route and capability flag remains OFF.

## Officially documented

- Manifold 3 supports Matrice 4D Series.
- Manifold provides media/sensor data acquisition, flight-control and route-planning development paths.
- Cloud API supports Dock 3 and Matrice 4D/4TD.

## Conflict/risk

Cloud API support documentation states Dock 3 with M4D/M4TD cannot currently support third-party payload. Therefore Dock + Manifold is not assumed.

## Hardware spikes

- camera stream and decoded frames
- wide/medium-tele/tele switching
- gimbal/aircraft yaw control
- FlyTo/hold/rejoin
- obstacle avoidance interaction
- Pilot/Cloud/PSDK authority
- Dock fit/power/charge
- thermal and resource benchmark

Every result must include firmware, SDK, aircraft, controller, test date and evidence.
