# Acceptance and Test Plan

## Required test layers

1. Unit geometry and risk tests
2. Recorded-flight replay
3. Simulation/HIL fault injection
4. Calibration range tests
5. Controlled equipment scenarios
6. Real-site shadow operations
7. Canary autonomy
8. Customer acceptance

## Mandatory acceptance themes

- server loss does not break onboard mission safety
- geo-localization error is measured, not assumed
- boundary uncertainty does not become a confirmed event
- active reobservation improves or declares unresolved
- coverage gaps are explicit
- event evidence and lineage are complete
- 3D model update is versioned and reversible
