# Reference Repositories

`repos/`에는 Git submodule로 세 저장소를 배치합니다.

이 디렉터리는 읽기 전용입니다. 일반 구현 Task에서 Commit, Format, Refactor하지 않습니다.

참고 코드를 실제 제품에 사용하려면:

1. Adoption Decision 작성
2. License/Data 검토
3. 필요한 최소 로직 추출 또는 이식
4. KSI 계약과 Error/Uncertainty 모델로 변경
5. Golden Test와 HIL 검증
6. 원출처 Commit을 ADR/코드 주석에 기록
