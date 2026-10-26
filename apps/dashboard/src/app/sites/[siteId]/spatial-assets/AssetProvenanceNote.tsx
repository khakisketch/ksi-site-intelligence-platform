"use client";

import { useEffect, useRef, useState } from "react";

import { formatKoreanDate } from "@/lib/datetime";
import { formatCountKo } from "@/lib/number-format";
import { capturePeriodTitle } from "@/lib/operator-language";
import type { SpatialAssetDescription } from "@/lib/core-api/spatial-asset-description";

const retentionLocusLabel: Record<SpatialAssetDescription["capture"]["originalRetentionLocus"], string> = {
  customer_workstation: "고객 작업장",
  upstream_source: "상위 출처",
  unknown: "미상",
};

const knowledgeLabel: Record<SpatialAssetDescription["producer"]["producerKnowledge"], string> = {
  DECLARED: "고객 제출 정보",
  PARTIAL: "일부 정보만 제출",
  UNKNOWN: "제작 정보 미상",
};

function nodataLabel(raster: NonNullable<SpatialAssetDescription["raster"]>): string {
  switch (raster.nodataRepresentation) {
    case "NONE":
      return "NoData 없음";
    case "FINITE":
      return raster.nodataValue === null ? "NoData 값 확인 불가" : `NoData 값 ${raster.nodataValue}`;
    case "NAN":
      return "NoData NaN";
    case "MASK":
      return "마스크 분리";
  }
}

/** 화면에 내놓기 전 최소 모양·신원 검사 — BFF의 엄격 검사를 통과하지 못한
 * 몸은 여기서도 두지 않는다. */
function isProvenanceView(value: unknown): value is SpatialAssetDescription {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  if (record.contractVersion !== "spatial-asset-description.v1") return false;
  if (typeof record.assetRef !== "string" || typeof record.siteId !== "string" || typeof record.workAreaId !== "string") return false;
  const producer = record.producer as Record<string, unknown> | null;
  const capture = record.capture as Record<string, unknown> | null;
  if (!producer || typeof producer !== "object" || !capture || typeof capture !== "object") return false;
  return (producer.producerKnowledge === "DECLARED" || producer.producerKnowledge === "PARTIAL" || producer.producerKnowledge === "UNKNOWN")
    && (capture.captureBasis === "EXACT_INTERVAL" || capture.captureBasis === "DATE_ONLY" || capture.captureBasis === "UNKNOWN")
    && (record.raster === null || (typeof record.raster === "object" && record.raster !== null));
}

function AssetProvenanceNoteBody({
  siteId,
  workAreaId,
  assetRef,
}: {
  siteId: string;
  workAreaId: string;
  assetRef: string;
}) {
  const [description, setDescription] = useState<SpatialAssetDescription | null>(null);
  const generationRef = useRef(0);
  useEffect(() => {
    const generation = ++generationRef.current;
    const controller = new AbortController();
    let cancelled = false;
    void (async () => {
      try {
        const response = await fetch(
          `/api/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/spatial-assets/${encodeURIComponent(assetRef)}/description`,
          { cache: "no-store", signal: controller.signal },
        );
        const value: unknown = await response.json().catch(() => null);
        // 늦게 도착한 이전 요청·취소된 요청은 버린다. 신원이 어긋난 몸은
        // 두지 않는다(다른 자료의 출처를 이 자리에 내놓지 않는다).
        if (cancelled || generationRef.current !== generation) return;
        if (!response.ok || !isProvenanceView(value)
          || value.assetRef !== assetRef || value.siteId !== siteId || value.workAreaId !== workAreaId) return;
        setDescription(value);
      } catch {
        // 판독 실패는 숨긴다 — 기본 카탈로그 사실이 이미 있다.
      }
    })();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [siteId, workAreaId, assetRef]);
  // 렌더 시점에도 신원을 재확인한다 — 키 없는 재사용에서도 다른 자료의
  // 출처를 내놓지 않는다.
  if (!description || description.assetRef !== assetRef || description.siteId !== siteId || description.workAreaId !== workAreaId) {
    return null;
  }
  const producerName = [description.producer.softwareName, description.producer.softwareVersion]
    .filter((part): part is string => typeof part === "string" && part.length > 0)
    .join(" ");
  const captureLine = description.capture.captureBasis === "EXACT_INTERVAL" && description.capture.captureStartedAt && description.capture.captureEndedAt
    ? capturePeriodTitle(description.capture.captureStartedAt, description.capture.captureEndedAt)
    : description.capture.captureBasis === "DATE_ONLY" && description.capture.captureDate
      ? `${formatKoreanDate(description.capture.captureDate)} · 날짜만 확인`
      : "관측 시점 미상";
  const digestEntries: Array<[string, string] | null> = [
    description.producer.buildIdentifier ? ["제작 빌드 확인값", description.producer.buildIdentifier] : null,
    description.producer.producerRunIdentifier ? ["제작 실행 확인값", description.producer.producerRunIdentifier] : null,
    description.capture.localInputManifestDigest ? ["입력 목록 확인값", description.capture.localInputManifestDigest] : null,
    description.raster ? ["검사 보고서 확인값", description.raster.sourceReportDigest] : null,
    description.raster ? ["검사 빌드 확인값", description.raster.inspectorBuildDigest] : null,
  ];
  const shownDigests = digestEntries.filter((entry): entry is [string, string] => entry !== null);
  return (
    <section aria-label="제작·촬영·격자 출처" className="rounded-lg border border-line bg-sunk/35 px-3 py-2.5">
      <dl className="grid gap-1.5 text-[12px] leading-5 text-ink-2">
        <div className="min-w-0">
          <dt className="text-[11px] text-ink-muted">제작</dt>
          <dd className="mt-0.5 break-words font-semibold text-ink-1">
            {producerName.length > 0 ? producerName : "제작 도구 정보 없음"} · {knowledgeLabel[description.producer.producerKnowledge]}
          </dd>
        </div>
        <div className="min-w-0">
          <dt className="text-[11px] text-ink-muted">촬영·원본 보관</dt>
          <dd className="mt-0.5 break-words font-semibold text-ink-1">
            {captureLine} · 원본 보관 {retentionLocusLabel[description.capture.originalRetentionLocus]}
          </dd>
        </div>
        <div className="min-w-0">
          <dt className="text-[11px] text-ink-muted">격자</dt>
          <dd className="mt-0.5 break-words font-semibold text-ink-1">
            {description.raster
              ? `${description.raster.bandCount}밴드 · ${description.raster.dtype} · ${description.raster.layout} · ${nodataLabel(description.raster)} · 유효 픽셀 ${formatCountKo(description.raster.validPixelCount)}`
              : "격자 측정 없음"}
          </dd>
        </div>
      </dl>
      {shownDigests.length > 0 && (
        <details className="mt-1 text-[11.5px] text-ink-2">
          <summary className="tap-target cursor-pointer font-semibold">확인값 보기</summary>
          <dl className="mt-1 grid gap-1 border-l-2 border-line pl-3">
            {shownDigests.map(([label, digest]) => (
              <div key={label} className="min-w-0">
                <dt className="text-ink-muted">{label}</dt>
                <dd className="break-all font-mono text-[11px]">{digest}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
    </section>
  );
}

/**
 * 자료의 제작·촬영·격자 출처 한 줄씩 — 카탈로그 뒤의 provenance와 검사
 * 격자 상세만 읽는다. 판독 실패·권한 없음·미지원이면 이 블록을 두지 않는다
 * (기본 카탈로그 사실이 이미 있으니 오류 벽을 세우지 않는다).
 *
 * 키로 범위를 묶어 자산이 바뀌면 이전 판독을 버리고 처음부터 다시 읽는다.
 * 본문도 키 없이 재사용될 수 있으므로 신원 반향을 렌더 전후로 확인한다.
 */
export function AssetProvenanceNote({
  siteId,
  workAreaId,
  assetRef,
}: {
  siteId: string;
  workAreaId: string;
  assetRef: string;
}) {
  return (
    <AssetProvenanceNoteBody
      key={`${siteId}|${workAreaId}|${assetRef}`}
      siteId={siteId}
      workAreaId={workAreaId}
      assetRef={assetRef}
    />
  );
}
