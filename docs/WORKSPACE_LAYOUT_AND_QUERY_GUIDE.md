# Workspace Layout and Query Guide

## 권장 실제 저장소 구조

```text
ksi-site-intelligence-platform/
├─ AGENTS.md
├─ CLAUDE.md
├─ README.md
├─ docs/
│  ├─ 00_READ_FIRST.md
│  ├─ product/
│  ├─ architecture/
│  ├─ acceptance/
│  ├─ security/
│  ├─ dji/
│  └─ reference/
├─ contracts/
│  ├─ schemas/
│  └─ api/
├─ apps/
│  └─ dashboard/
├─ services/
│  ├─ core/
│  ├─ dji-gateway/
│  └─ processing-controller/
├─ edge/
│  └─ manifold-runtime/
├─ workers/
│  ├─ reconstruction-odm/
│  ├─ change-detection/
│  ├─ map-compiler/
│  └─ dataset-builder/
├─ packages/
│  ├─ domain/
│  ├─ geo-core/
│  ├─ event-contracts/
│  ├─ mission-contracts/
│  └─ test-vectors/
├─ tests/
│  ├─ contract/
│  ├─ golden/
│  ├─ replay/
│  ├─ hil/
│  └─ e2e/
├─ references/
│  ├─ REFERENCE_REPOS_LOCK.yaml
│  └─ repos/
│     ├─ ksi-platform/   # Git submodule, read-only
│     ├─ ksi-terra/      # Git submodule, read-only
│     └─ ksi-scout/      # Git submodule, read-only
├─ scripts/
└─ templates/
```

## 왜 Submodule인가

- 참고 시점의 Commit을 재현할 수 있다.
- 기존 저장소 History를 보존한다.
- 새 제품 Code와 물리적으로 구분된다.
- AI Agent가 한 Workspace 안에서 검색할 수 있다.
- 소스 복사로 인한 License·Provenance 손실을 줄인다.

참고 저장소를 `apps/`나 `services/` 아래에 두지 않는다. Build와 Test 대상에서도 제외한다.

## Agent 실행

Codex와 Claude Code는 `ksi-site-intelligence-platform/` 루트에서 실행한다.

Submodule 초기화:

```bash
git submodule update --init --recursive
git submodule status
```

## 검색 순서

### 1. 요구사항 검색

```bash
./scripts/qspec "Mission Contract"
./scripts/qspec "통신 단절"
```

### 2. 참고정책 검색

```bash
./scripts/qrefdocs "TelemetryInterpolator"
./scripts/qrefdocs "JobRunner"
```

### 3. 실제 참고 코드 검색

```bash
./scripts/qrefcode "class TelemetryInterpolator"
./scripts/qrefcode "class JobRunner"
./scripts/qrefcode "EventCandidate"
```

### 4. 신규 구현 검색

```bash
./scripts/qimpl "MissionContract"
```

## 좋은 Agent 질의

```text
REQ-EDGE-SYNC-001을 구현한다.
먼저 AGENTS.md와 docs/00_READ_FIRST.md를 읽어라.
Scout의 TelemetryInterpolator와 Platform의 sensor synchronization 구현을 참고하되
참고 저장소를 수정하거나 import하지 마라.
Adoption Decision, 변경할 계약, 대상 파일, 테스트와 HIL 가정을 먼저 제시한 뒤 구현하라.
```

## 나쁜 Agent 질의

```text
Scout 기능을 새 프로젝트에 옮겨줘.
```

범위·소유권·수용기준이 없어서 과거 구조를 그대로 복제할 위험이 있다.
