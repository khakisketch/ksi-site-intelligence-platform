"use client";

import { useState } from "react";

import type { DefectCandidate } from "@/lib/core-api/types";

/**
 * 결함 후보 폴리곤을 사진 위에 겹쳐 그린다.
 *
 * ## 왜 SVG 인가
 *
 * 폴리곤은 원본 픽셀 좌표(수천 px)이고 화면은 그보다 작다. SVG `viewBox` 를 원본
 * 화소수로 잡으면 브라우저가 배율을 알아서 맞춰준다 — 좌표를 손으로 스케일하면
 * 그 계산이 반응형 리사이즈마다 어긋날 자리가 된다. canvas 는 확대 시 계단이 생기고
 * 개별 도형에 이벤트를 걸 수 없다.
 *
 * ## 배율 기준은 서버가 준 화소수다
 *
 * 이미지가 로드된 뒤 `naturalWidth` 를 읽어 쓰지 않는다. 서버가 원장에 등록된
 * 화소수를 함께 내려주므로(`GET .../source-media/{id}/view`) 로드 전에 레이아웃을
 * 잡을 수 있고, 무엇보다 **등록값과 실제 이미지가 다르면 그 사실이 화면에 드러난다**
 * — 로드된 이미지 크기로 맞춰버리면 그 불일치가 조용히 묻힌다. Core 는 결함 후보의
 * `imageSize` 를 이미 등록 화소수와 대조해 거부하므로(`IMAGE_SIZE_MISMATCH`),
 * 여기 도달한 폴리곤은 이 좌표계 안에 있다.
 */
export function DefectOverlay({
  viewUrl,
  width,
  height,
  candidates,
}: {
  viewUrl: string;
  width: number;
  height: number;
  candidates: DefectCandidate[];
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);

  return (
    <div className="flex flex-col gap-2">
      <div className="relative overflow-hidden rounded-lg border border-neutral-200">
        {/* 업로드 전이거나 URL 이 만료됐으면 이미지가 안 뜬다 — 폴리곤만 남기지 않고
            그 사실을 말한다(빈 사각형에 선만 떠 있으면 무엇이 잘못됐는지 모른다). */}
        {loadFailed ? (
          <div className="flex aspect-[4/3] items-center justify-center bg-neutral-100 p-4 text-center text-sm text-neutral-500">
            사진을 불러오지 못했습니다. 아직 업로드되지 않았거나 열람 링크가
            만료됐을 수 있습니다.
          </div>
        ) : (
          // presigned URL 은 배포마다 호스트가 달라 next/image 의 remotePatterns
          // allowlist 로 고정할 수 없다(빌드 시점에 알 수 없는 값이다). 문서도
          // 인증이 필요한 원격 이미지는 최적화를 끄라고 안내한다 —
          // 최적화를 끈 next/image 는 <img> 와 하는 일이 같으면서 도메인 설정만
          // 더 요구하므로 여기서는 <img> 를 쓴다.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={viewUrl}
            alt=""
            width={width}
            height={height}
            className="block h-auto w-full"
            onError={() => setLoadFailed(true)}
          />
        )}
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="pointer-events-none absolute inset-0 h-full w-full"
          aria-label={`결함 후보 ${candidates.length}건`}
        >
          {candidates.map((candidate) => {
            const polygon = candidate.geometry.payload;
            if (polygon === null || polygon.length < 3) return null;
            const isSelected = selected === candidate.defectCandidateId;
            return (
              <polygon
                key={candidate.defectCandidateId}
                points={polygon.map(([x, y]) => `${x},${y}`).join(" ")}
                // 선 굵기를 원본 화소 기준으로 두면 축소 시 실선처럼 사라진다 —
                // vector-effect 로 화면 기준 굵기를 유지한다.
                vectorEffect="non-scaling-stroke"
                className={
                  isSelected
                    ? "fill-amber-400/40 stroke-amber-500 stroke-2"
                    : "fill-red-500/20 stroke-red-500 stroke-1"
                }
              />
            );
          })}
        </svg>
      </div>

      <ul className="flex flex-col gap-1 text-sm">
        {candidates.map((candidate) => (
          <li key={candidate.defectCandidateId}>
            <button
              type="button"
              onMouseEnter={() => setSelected(candidate.defectCandidateId)}
              onMouseLeave={() => setSelected(null)}
              onFocus={() => setSelected(candidate.defectCandidateId)}
              onBlur={() => setSelected(null)}
              className={`w-full rounded px-2 py-1 text-left ${
                selected === candidate.defectCandidateId
                  ? "bg-amber-50"
                  : "hover:bg-neutral-50"
              }`}
            >
              <span className="font-mono text-xs">{candidate.defectCandidateId}</span>
              <span className="ml-2 text-neutral-600">
                신뢰도 {(candidate.confidence * 100).toFixed(1)}%
                {candidate.measurements?.areaPx2 !== undefined &&
                  ` · ${candidate.measurements.areaPx2.toFixed(0)} px²`}
                {candidate.geometry.payload === null && " · 형상 없음"}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
