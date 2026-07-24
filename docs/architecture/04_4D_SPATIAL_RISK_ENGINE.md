# 4D Spatial Perception and Risk Engine

## Core thesis

KSI's moat is not YOLO. It is the conversion of detections into temporally consistent, geo-referenced entities and automatic equipment-derived risk volumes.

## Pipeline

Detection/Segmentation/Keypoints -> Track -> Camera ray -> Site coordinate -> Multi-view fusion -> Entity pose/covariance -> Equipment kinematics -> Predicted risk field -> Event or active reobservation.

## Equipment packs

Each supported equipment type has its own part model, pose schema, kinematic constraints, reachable/swept volume, risk policy and benchmark.

## Manual zones

Manual geometry is allowed for site boundary, legal/no-fly, privacy and fixed operational policy. It is not the primary method for mobile equipment hazards.

## Risk evaluation

Risk considers current overlap, predicted closest approach, time to collision, hazard severity, occlusion and uncertainty. Boundary uncertainty triggers reobservation rather than automatic confirmation.
