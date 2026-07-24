# DJI Capability Verification Matrix

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
