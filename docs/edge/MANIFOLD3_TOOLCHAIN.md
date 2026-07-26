# Manifold 3 Toolchain Manifest

- 상태: Stage C-3 (골격 단계) — **호스트 빌드만 검증됨, 타깃 크로스빌드 미검증**
- 대상: DJI Manifold 3 온보드 컴퓨터 (MASTER_PRD §9.1)

## 1. 현재 검증된 것 / 아닌 것

정직하게 구분한다 — 미검증 항목을 "지원"으로 표시하지 않는다(INV-041과 같은 원칙).

| 항목 | 상태 | 근거 |
|---|---|---|
| 호스트(x86-64/aarch64 Linux) C++17 빌드 | **검증됨** | `cmake 3.28 + g++ 13.3`, `-Wall -Wextra -Wpedantic -Werror` 통과, ctest green |
| control plane 계약 테스트 | **검증됨** | 33개 단언 통과 + 변이 테스트로 하네스 유효성 확인 |
| Manifold 3 타깃 크로스빌드 | **미검증** | 실기 미보유 — 장비 세션에서 검증 |
| PSDK 링크·카메라/짐벌 API | **미검증(SPIKE_REQUIRED)** | Capability Registry `SPIKE-DJI-01`~`09` 참조 |
| CUDA/TensorRT 추론 파이프라인 | **미착수** | Phase 1 이후 범위 |

## 2. 타깃 하드웨어 (공식 사양, 실측 아님)

- Manifold 3: 16GB LPDDR5, 256GB SSD, 최대 100 TOPS (Master PRD §1.2 B, [R1][R2])
- 최대 TOPS는 특정 INT8 희소 연산 조건의 **이론값**이다 — 실제 모델 처리량은 장비
  시험으로 결정한다(PRD가 명시한 단서를 그대로 유지한다).
- 아키텍처: aarch64 (NVIDIA Jetson 계열)

## 3. 빌드 (현재 골격)

```bash
cd edge/manifold-runtime
cmake -S . -B build -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build -j
ctest --test-dir build --output-on-failure
```

의존성: **없음**(순수 C++17 표준 라이브러리). 외부 테스트 프레임워크를 쓰지 않는 이유는
네트워크 fetch 없이 CI에서 그대로 돌아야 하기 때문이다.

## 4. 타깃 툴체인 계획 (실기 도착 후 확정)

아래는 계획이며 **아직 검증되지 않았다.** 실기 검증 시 이 표를 실측값으로 갱신하고
Capability Registry에 증거와 함께 기록한다.

| 구성 | 계획값 | 확정 방법 |
|---|---|---|
| 타깃 트리플 | `aarch64-linux-gnu` | 실기 `uname -m` |
| C++ 표준 | C++17 (PRD §9.1 "C++17 이상") | 유지 |
| 컴파일러 | JetPack 동봉 GCC | 실기 `g++ --version` |
| CUDA/TensorRT | JetPack 버전 종속 | 실기 확인 |
| PSDK | DJI Payload SDK (버전 미확정) | SPIKE-DJI-01~09 |
| CMake 크로스 파일 | `cmake/toolchain-manifold3.cmake` (미작성) | 실기 세션 |

## 5. 금지 사항 (Stage C 범위 제약)

승인된 Stage C 범위는 계약·빌드·상태전이 골격까지다. 다음은 실기/HIL 증거 전까지 금지:

- 실제 PSDK 비행명령 활성화
- Capability Registry에서 DJI 기능을 `VERIFIED`로 승격
- Python에서 DJI Flight Command 직접 호출
- 실기 증거 없이 M4D 카메라·짐벌·비행 API가 작동한다고 선언

현재 `ksi_control_plane` 라이브러리에는 기체를 움직이는 코드 경로가 **존재하지 않는다** —
명령 유효성 판정과 안전 상태 계산만 한다.
