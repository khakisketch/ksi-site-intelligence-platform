# Workspace Layout and Query Guide

> Repository responsibility, runtime boundary, and canonical path are governed by
> [`../REPOSITORY_STRUCTURE.md`](../REPOSITORY_STRUCTURE.md). This guide covers workspace search and
> query mechanics only. Document authority/status is indexed by
> [`DOCUMENT_STATUS.md`](DOCUMENT_STATUS.md).

## 현행 책임 중심 진입점

이 문서에는 디렉터리 트리를 복제하지 않는다. 복제된 트리는 실제 코드가 변할 때 조용히
낡기 때문이다. 전체 현행 구조는 `REPOSITORY_STRUCTURE.md`를 사용한다. R0-R2 당시 이름
문제와 제안은 `docs/audit/REPOSITORY_NAMING_AND_OWNERSHIP_AUDIT_R0_R2.md`의 역사적
증거이고, 실행된 service/package 이동은 `docs/audit/REPOSITORY_MIGRATION_MANIFEST_R3.json`
이 옛 경로와 현재 경로를 연결한다.

| 제품 책임 | 시작 경로 |
|---|---|
| KSI Operations Console | `apps/dashboard/README.md` |
| KSI Site Intelligence Core / Processing | `services/README.md` |
| Manifold Edge / PSDK (P3 Task 6 historical) | `archive/acquisition-2026/edge/README.md` |
| 재사용 domain/contract/algorithm | `packages/README.md` |
| wire/API/HIL schema | `contracts/` |
| 문서 authority/status | `docs/00_READ_FIRST.md`, `docs/DOCUMENT_STATUS.md` |
| 검증 계층 | `REPOSITORY_STRUCTURE.md`의 Verification ownership |
| 참고 구현 | `references/README.md` |

`services/`에는 독립적으로 시작·감시·배포하는 process만 둔다. 다른 KSI process가
import하며 독립 lifecycle이 없는 계산·geometry·model adapter는 `packages/`에서 찾는다.
경로 이름만으로 판단하지 말고 해당 README, `pyproject.toml`, 실제 entrypoint/consumer와
owner test를 대조한다.

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
