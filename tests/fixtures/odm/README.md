# ODM 실물 산출물 픽스처

`pacifica_all_zip_entries.txt` — 무수정 `opendronemap/nodeodm:latest`(NodeODM
2.2.4 / ODM 3.5.6)가 실제로 만든 `all.zip` 의 엔트리 목록이다.

- 입력: OpenDroneMap `odm_data_pacifica` 12장(CC BY-SA 4.0, Michele Tobias)
- 옵션: `--dsm --dtm --pc-quality medium`
- 실행: 2026-08-06, 20코어에서 3.0분, 아카이브 84.4MB

**목록만 두고 아카이브(84MB)와 사진(67MB)은 커밋하지 않는다** — 저장소를 무겁게
하고, 데이터셋이 CC BY-SA 라 재배포에 share-alike 의무가 따라붙는다. 경로 매핑이
실물과 어긋나는 것을 잡는 데는 이름 목록으로 충분하다.

이 파일이 있는 이유: `ODM_ASSETS` 의 `archive_entry` 를 파일 이름만 보고 정했다가
`cameras.json`(카메라 내부 파라미터)을 카메라 포즈로 잘못 매핑한 적이 있다.
그 종류의 오류는 실물 목록과 대조해야만 잡힌다.
