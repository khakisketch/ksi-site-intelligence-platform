# KSI-Terra License Compliance Plan

> 기술적 준수계획이며 법률의견서가 아니다.

## 1. 자체 코드 권리

- 루트 License/Proprietary notice 추가
- 기여자별 IP 귀속 확인
- 외주·공동개발 계약 확인
- 복사된 코드의 출처 기록
- AI 생성 코드의 유사성 검토 절차
- Contributor provenance log

## 2. 제3자 인벤토리

필수 산출:

- SPDX 또는 CycloneDX SBOM
- Python dependency license report
- NPM dependency license report
- Container image package inventory
- Model weight registry
- Dataset rights registry
- Font/map tile/data license registry

## 3. AGPL 정책

ODM/NodeODM:

- 별도 프로세스·별도 이미지
- KSI proprietary code를 AGPL repository에 포함하지 않음
- 수정 fork와 source offer 관리
- 고객사 배포 전 법무 승인
- remote network use 검토
- 버전·소스 URL·patch set 보존

## 4. Permissive OSS

Apache/BSD/MIT 구성요소:

- copyright/license text 보존
- NOTICE 요구사항 확인
- binary distribution notices 생성
- 수정 내역 기록
- trademark를 제품 보증처럼 사용하지 않음

## 5. Proprietary Engine

Metashape 등:

- 일반 라이선스와 Service Provider License를 구분
- 고객 제공 라이선스와 KSI 제공 서비스를 구분
- 자동화·SaaS·네트워크 처리 권한을 계약서로 확인
- 기본 제품 의존성으로 두지 않음

## 6. 배포 게이트

다음 중 하나라도 실패하면 Release를 차단한다.

- Unknown license
- Prohibited/copyleft policy violation
- 모델 weight 권리 미확인
- 데이터셋 상업 이용 미확인
- 필수 NOTICE 누락
- AGPL patch source offer 누락
- 사내 코드 IP 귀속 미확인
