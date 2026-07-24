# Private Reference Submodule 인증 정책

- 상태: 확정 (2026-07-25, 대표자 반영사항 3)
- 결정: **fine-grained Personal Access Token** (GitHub App 미채택)

## 결정 근거

- 참고 레포 3개(`ksi-platform`, `KSI-Terra`, `KSI-Scout`)와 본 레포는 모두 단일 계정
  (`khakisketch`) 소유의 private 레포다. 조직·다계정 위임이 없어 GitHub App의 설치·키관리
  오버헤드가 실익 없다.
- fine-grained PAT는 **대상 레포 4개 + Contents: Read-only**로 최소권한 스코프가 가능하다.

## 현재 CI는 토큰이 필요 없다

`.github/workflows/ci.yml`은 서브모듈을 클론하지 않는다.

- 테스트·가드는 자체 코드만 검사한다 (references는 빌드·테스트 제외가 원칙).
- 핀 드리프트는 `scripts/verify_reference_pins.sh`가 **gitlink SHA(`git ls-tree`)**로 검증한다
  — 서브모듈 콘텐츠 없이 동작.
- workflow `permissions: contents: read` 고정.

## 서브모듈 실콘텐츠가 필요한 job이 생길 때 (예: golden vector 재추출 CI)

1. GitHub → Settings → Developer settings → Fine-grained tokens 생성:
   - Repository access: `ksi-site-intelligence-platform`, `ksi-platform`, `KSI-Terra`, `KSI-Scout`
   - Permissions: Contents **Read-only** (그 외 전부 No access)
   - 만료: 90일 이하, 만료 시 회전
2. 본 레포 Secrets에 `REFERENCE_REPOS_TOKEN`으로 저장.
3. 해당 job에서만:

```yaml
- uses: actions/checkout@v4
  with:
    submodules: recursive
    token: ${{ secrets.REFERENCE_REPOS_TOKEN }}
```

4. 토큰이 없는 fork/외부 PR에서는 해당 job을 skip 처리한다 (`if: ${{ secrets... != '' }}` 게이트).

## 금지

- classic PAT(전체 repo 스코프) 사용 금지.
- workflow 권한을 `contents: write` 이상으로 올리지 않는다 (배포 워크플로는 별도 파일·별도 승인).
