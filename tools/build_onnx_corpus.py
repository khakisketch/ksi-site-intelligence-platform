"""PyTorch↔ONNX 비교 corpus 생성기 (B2 선결 — 대표자 지정 2026-07-28).

두 PD 원본(models/test-assets/person.jpg — Lange "Migrant Mother" 1936 미 정부
작품 / car.jpg — 1925 Ford, 네덜란드 국립문서보관소 PD)에서 지정 10종 장면을
**결정적으로** 파생한다(시드 고정, PIL 연산만). 산출물은 models/ 아래(gitignore)
— 이미지 실물은 git 에 넣지 않고 이 생성기와 테스트만 커밋한다.

사용법::

    uv run python tools/build_onnx_corpus.py

각 장면의 의도:
    single_person       사람 1명 크롭(원본 좌하 — 어머니·아기 영역)
    multiple_people     원본 전체(어머니+아이들)
    no_detection        단색 배경(구조 없음)
    small_person        원본 1/5 축소 후 대형 캔버스 구석 배치
    border_person       인물이 프레임 오른쪽 경계에 절반 걸침(클리핑 유발)
    overlap_people      원본(인물 겹침 실재 — 아이들이 어머니에 기댐)
    non_person_car      car.jpg(차량 — 지원 클래스, Person 아님)
    unsupported_scene   원본(저 threshold 에서 미지원 클래스 후보 동반)
    low_conf_noise      시드 고정 노이즈(저신뢰 후보 유발)
    clipping_scene      border_person 과 동일 계열의 큰 걸침(과도 클리핑 후보)
"""

from __future__ import annotations

import sys
from pathlib import Path

ASSETS = Path("models/test-assets")
CORPUS = ASSETS / "onnx-corpus"


def build() -> int:
    import numpy as np
    from PIL import Image

    person_path = ASSETS / "person.jpg"
    car_path = ASSETS / "car.jpg"
    for required in (person_path, car_path):
        if not required.is_file():
            print(f"✗ 원본 없음: {required} (README 의 PD 원본 확보 절차 참조)", file=sys.stderr)
            return 1
    CORPUS.mkdir(parents=True, exist_ok=True)

    person = Image.open(person_path).convert("RGB")
    car = Image.open(car_path).convert("RGB")
    pw, ph = person.size

    scenes: dict[str, Image.Image] = {}

    # 1) 사람 1명 — 좌측 절반 하단 크롭(어머니 얼굴·상반신 영역)
    scenes["single_person"] = person.crop((0, int(ph * 0.15), int(pw * 0.62), ph))
    # 2) 다수 인물 — 원본
    scenes["multiple_people"] = person.copy()
    # 3) 무탐지 — 단색(구조 없음)
    scenes["no_detection"] = Image.new("RGB", (640, 480), (96, 112, 128))
    # 4) 작은 인물 — 1/5 축소 후 1280x960 캔버스 우하단
    small = person.resize((pw // 5, ph // 5), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (1280, 960), (70, 80, 90))
    canvas.paste(small, (1280 - small.width - 20, 960 - small.height - 20))
    scenes["small_person"] = canvas
    # 5) 경계 걸침 — 인물 절반이 오른쪽 프레임 밖
    border = Image.new("RGB", (pw, ph), (70, 80, 90))
    border.paste(person, (pw // 2, 0))  # 오른쪽 절반만 프레임 안
    scenes["border_person"] = border
    # 6) 겹침 — 원본(아이들이 어머니에 기대 실제 겹침)
    scenes["overlap_people"] = person.copy()
    # 7) 비Person 지원 클래스 — 차량
    scenes["non_person_car"] = car.copy()
    # 8) 미지원 클래스 동반 장면 — 원본(저 threshold 에서 미지원 후보가 관측됨)
    scenes["unsupported_scene"] = person.copy()
    # 9) 저신뢰 노이즈 — 시드 고정
    rng = np.random.default_rng(20260728)
    scenes["low_conf_noise"] = Image.fromarray(
        rng.integers(0, 255, (480, 640, 3), dtype=np.uint8), mode="RGB"
    )
    # 10) 과도 클리핑 후보 — 인물 대부분이 프레임 밖(하단 1/4 만 안)
    clipping = Image.new("RGB", (pw, ph), (70, 80, 90))
    clipping.paste(person, (0, int(ph * 0.75)))
    scenes["clipping_scene"] = clipping

    for name, image in sorted(scenes.items()):
        out = CORPUS / f"{name}.png"  # PNG — JPEG 재인코딩 비결정성 제거
        image.save(out, format="PNG")
        print(f"✓ {out} {image.size}")
    print(f"\n완료: {len(scenes)}종 → {CORPUS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
