"use client";

import Link from "next/link";
import { useState } from "react";
import { DEFAULT_MATERIALS_DESIGN_RETURN } from "@/lib/design-preview-return";

import { SpatialWorkbenchFrame } from "@/components/site/SpatialWorkbenchFrame";
import { SpatialSwipeCompare } from "@/components/site/SpatialSwipeCompare";
import {
  useDirectViewport,
  ViewportResetButton,
} from "@/app/sites/[siteId]/DirectDisplayViewport";

/**
 * 디자인 예시 — 화면 구성만 보여주는 별도 경로.
 *
 * - 이 화면은 어떤 등록 자료·관측·제출·검사·분석 기록에도 묶이지 않는다.
 *   현장 DTO·자산 참조·준비 식별자·권한 판정을 만들지 않으며, Core를
 *   호출하지 않는다(앱 셸·인증 제외).
 * - 두 칸의 사진은 공개 해안 관측의 보기용 크롭(CC BY 4.0)이며, 현재 등록
 *   자료·측정값·정합·분석 근거가 아니다. 각 칸은 독립된 보기다.
 * - 실제 등록 자료는 위 배너의 돌아가기 링크에서 본다. 예시에서 등록·
 *   준비·검사를 새로 만들 수 없다.
 *
 * Invariants: INV-020(발행처 표기일 그대로, 정확한 시각 미상)/
 * INV-040(명시적 예시 표기, 실패한 실제 바이트의 fallback 금지 — 이 경로는
 * 자동 진입·대체가 없고 사용자가 직접 연다)/INV-051(보기용 파생 크롭이며
 * 원본 권위가 아님)/INV-053(수치·비교·정합 주장 없음)/INV-060·061(등록
 * 조회·쓰기·반출 없음, 같은 출처 정적 파일만 둔다).
 */

type ExampleLayer = "ortho" | "dsm";
type ExampleSide = "A" | "B";
export type ExampleMode = "single" | "compare" | "swipe";

const EXAMPLE_MODE_ORDER: readonly ExampleMode[] = ["single", "compare", "swipe"];

function modeLabel(mode: ExampleMode): string {
  if (mode === "single") return "한 장";
  if (mode === "swipe") return "밀어서 비교";
  return "나란히";
}

interface ExampleObservation {
  id: "obs-2021" | "obs-2022";
  /** 발행처 표기일 — 정확한 촬영 시각이 아니다. */
  dateLabel: string;
  orthoSrc: string;
  dsmSrc: string;
}

const OBSERVATIONS: readonly ExampleObservation[] = [
  {
    id: "obs-2021",
    dateLabel: "2021-08-17",
    orthoSrc: "/design-preview/spatial/ortho-2021.webp",
    dsmSrc: "/design-preview/spatial/dsm-2021.webp",
  },
  {
    id: "obs-2022",
    dateLabel: "2022-08-24",
    orthoSrc: "/design-preview/spatial/ortho-2022.webp",
    dsmSrc: "/design-preview/spatial/dsm-2022.webp",
  },
];

const SOURCE_LINE = "Cambridge Coastcare / DataWA · CC BY 4.0 · 보기용 크롭";
const LICENSE_HREF = "https://creativecommons.org/licenses/by/4.0/";

function layerLabel(layer: ExampleLayer): string {
  return layer === "ortho" ? "정사영상" : "DSM";
}

/**
 * 예시 한 칸 — 같은 직접 조작 표시 규칙(끌기·휠·키보드·전체 보기)으로
 * 정적 크롭만 둔다. 준비·검사·측정·다운로드 흐름은 두지 않는다. 칸은
 * 무대 높이에 맞춰 들어간다 — 세로 사진을 화면 밖으로 늘리지 않으며,
 * 가로로 늘이지 않는다(object-contain).
 */
function ExamplePane({
  side,
  observation,
  layer,
  onObservationChange,
  onLayerChange,
}: {
  side: ExampleSide;
  observation: ExampleObservation;
  layer: ExampleLayer;
  onObservationChange: (id: ExampleObservation["id"]) => void;
  onLayerChange: (layer: ExampleLayer) => void;
}) {
  const viewport = useDirectViewport();
  const src = layer === "ortho" ? observation.orthoSrc : observation.dsmSrc;
  const selectId = `example-observation-${side}`;
  return (
    <div data-workbench-pane className="flex min-w-0 flex-col gap-1.5 md:px-3 md:first:pl-0 md:last:pr-0 lg:h-full lg:min-h-0">
      <div data-workbench-pane-controls className="flex min-w-0 shrink-0 flex-wrap items-center gap-x-2 gap-y-1">
        <span aria-hidden="true" className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-sunk text-[11px] font-bold">{side}</span>
        <span className="sr-only">{side} 칸</span>
        <label className="sr-only" htmlFor={selectId}>{side} 관측 선택</label>
        <select
          id={selectId}
          value={observation.id}
          onChange={(event) => onObservationChange(event.target.value as ExampleObservation["id"])}
          className="input min-w-0 max-w-44 text-[12.5px]"
        >
          {OBSERVATIONS.map((candidate) => (
            <option key={candidate.id} value={candidate.id}>
              {candidate.dateLabel}
            </option>
          ))}
        </select>
        <div className="flex shrink-0 gap-1" role="group" aria-label={`${side} 층 선택`}>
          {(["ortho", "dsm"] as const).map((candidate) => (
            <button
              key={candidate}
              type="button"
              aria-pressed={layer === candidate}
              onClick={() => onLayerChange(candidate)}
              className={`tap-target inline-flex items-center rounded-md px-3 py-1.5 text-[12.5px] break-keep ${layer === candidate ? "bg-sunk font-bold" : "text-ink-2"}`}
            >
              {layerLabel(candidate)}
            </button>
          ))}
        </div>
      </div>
      <div
        {...viewport.frameProps}
        aria-label={`${side} · ${observation.dateLabel} 보기용 크롭. 직접 끌어서 보고, 휠·두 손가락·두 번 두드리기로 확대합니다. 그림을 선택하면 방향키·Home 키도 쓸 수 있습니다.`}
        className="relative w-full cursor-grab overflow-hidden bg-sidebar focus-visible:outline-2 focus-visible:outline-offset-2 active:cursor-grabbing lg:min-h-0 lg:flex-1"
      >
        <div {...viewport.contentProps} className="relative h-full w-full">
          {/* 정적 예시 크롭 — 빌드타임 최적화 대상이 아니다. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={src}
            alt=""
            aria-hidden="true"
            className="block h-auto w-full lg:absolute lg:inset-0 lg:h-full lg:w-full lg:object-contain"
            draggable={false}
          />
        </div>
        <ViewportResetButton onReset={viewport.reset} />
      </div>
      {viewport.note && (
        <p className="shrink-0 text-[12px] leading-5 text-ink-2" role="status">{viewport.note}</p>
      )}
    </div>
  );
}

function ObservationPicker({
  side,
  value,
  onChange,
}: {
  side: ExampleSide;
  value: ExampleObservation["id"];
  onChange: (id: ExampleObservation["id"]) => void;
}) {
  return (
    <fieldset className="flex min-w-0 flex-col gap-1">
      <legend className="px-1.5 pb-1 text-[12px] font-bold text-ink-muted">
        {side === "A" ? "A(왼쪽·한 장) 관측" : "B(오른쪽) 관측"}
      </legend>
      <div className="flex min-w-0 flex-col gap-1">
        {OBSERVATIONS.map((observation) => {
          const selected = observation.id === value;
          return (
            <button
              key={observation.id}
              type="button"
              aria-pressed={selected}
              title={selected ? `${observation.dateLabel} · 보는 중 · 발행처 표기일, 정확한 시각 미상` : `${observation.dateLabel} · 발행처 표기일, 정확한 시각 미상`}
              onClick={() => onChange(observation.id)}
              className={`tap-target flex min-w-0 items-center gap-2 rounded-md px-1.5 py-1.5 text-left ${selected ? "bg-sunk" : ""}`}
            >
              <span aria-hidden="true" className="h-10 w-14 shrink-0 overflow-hidden rounded border border-line bg-sunk">
                {/* 정적 예시 축소 — 빌드타임 최적화 대상이 아니다. */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={observation.orthoSrc} alt="" className="block h-full w-full object-cover" draggable={false} />
              </span>
              <span className="min-w-0">
                <span className={`block break-words text-[12.5px] leading-snug ${selected ? "font-bold" : "font-semibold"}`}>
                  {side} · {observation.dateLabel}{selected ? " · 보는 중" : ""}
                </span>
                <span className="block text-[11.5px] text-ink-2">시각 미상</span>
              </span>
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

export default function MaterialsDesignPreview({
  returnHref = DEFAULT_MATERIALS_DESIGN_RETURN,
  initialMode = "compare",
}: { returnHref?: string; initialMode?: ExampleMode }) {
  const [mode, setMode] = useState<ExampleMode>(initialMode);
  const [sideAObservation, setSideAObservation] = useState<ExampleObservation["id"]>("obs-2021");
  const [sideBObservation, setSideBObservation] = useState<ExampleObservation["id"]>("obs-2022");
  const [layerA, setLayerA] = useState<ExampleLayer>("ortho");
  const [layerB, setLayerB] = useState<ExampleLayer>("ortho");
  const [infoOpen, setInfoOpen] = useState(false);
  const [swipeBoundary, setSwipeBoundary] = useState(50);
  // 겹쳐 보기의 공유 카메라 — 두 층이 같은 transform 하나로 움직인다.
  // 층별 독립 카메라는 두지 않는다.
  const swipeViewport = useDirectViewport();

  const observationA = OBSERVATIONS.find((item) => item.id === sideAObservation) ?? OBSERVATIONS[0]!;
  const observationB = OBSERVATIONS.find((item) => item.id === sideBObservation) ?? OBSERVATIONS[1]!;
  const compareMode = mode === "compare";
  const swipeMode = mode === "swipe";
  const swipeLayersMatch = layerA === layerB;
  const swipeSameObservation = sideAObservation === sideBObservation;
  const setBothLayers = (layer: ExampleLayer) => {
    setLayerA(layer);
    setLayerB(layer);
  };

  return (
    <div className="flex w-full min-w-0 min-h-0 flex-1 flex-col px-2 py-2 sm:px-3">
      <h2 className="sr-only">디자인 예시</h2>
      <SpatialWorkbenchFrame
        contextBar={
          <>
            <span className="min-w-0 shrink-0 truncate text-[12px] leading-5 text-ink-2">
              <strong className="font-bold text-ink-1">디자인 예시 · 현재 등록 자료 아님</strong>
              {" · "}
              <Link className="tap-target font-semibold underline" href={returnHref}>
                실제 등록 자료로 돌아가기
              </Link>
            </span>
            <div className="flex shrink-0 gap-1" role="group" aria-label="보기 방식">
              {EXAMPLE_MODE_ORDER.map((candidate) => (
                <button
                  key={candidate}
                  type="button"
                  aria-pressed={mode === candidate}
                  onClick={() => setMode(candidate)}
                  className={`tap-target rounded-md px-3 py-1.5 text-[12.5px] break-keep ${mode === candidate ? "bg-sunk font-bold" : "text-ink-2"}`}
                >
                  {modeLabel(candidate)}
                </button>
              ))}
            </div>
            <button
              data-workbench-info-trigger
              type="button"
              aria-expanded={infoOpen}
              aria-controls="design-example-info"
              onClick={() => setInfoOpen(!infoOpen)}
              className={`tap-target shrink-0 text-[12px] underline ${infoOpen ? "font-semibold" : "text-ink-2"}`}
            >
              정보
            </button>
            <span className="ml-auto flex shrink-0 items-center">
              <Link href="/sites" className="tap-target shrink-0 text-[12px] underline decoration-dotted text-ink-2">
                실제 현장에서 등록
              </Link>
            </span>
          </>
        }
        catalog={
          <div className="flex min-w-0 flex-col gap-1">
            <ObservationPicker side="A" value={sideAObservation} onChange={setSideAObservation} />
            {compareMode && (
              <ObservationPicker side="B" value={sideBObservation} onChange={setSideBObservation} />
            )}
          </div>
        }
        catalogLabel="관측 선택"
        stage={
          <section aria-label={swipeMode ? "예시 겹쳐 보기" : compareMode ? "예시 두 관측 나란히 보기" : "예시 관측 한 장 보기"} className="flex h-full min-w-0 flex-col gap-2 overflow-y-auto">
            {swipeMode ? (
              <>
                <div data-workbench-pane-controls className="flex min-w-0 shrink-0 flex-wrap items-center gap-x-2 gap-y-1">
                  <div className="flex min-w-0 shrink-0 items-center gap-2">
                  <span aria-hidden="true" className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-sunk text-[11px] font-bold">A</span>
                  <label className="sr-only" htmlFor="example-swipe-observation-a">A 관측 선택</label>
                  <select
                    id="example-swipe-observation-a"
                    value={observationA.id}
                    onChange={(event) => setSideAObservation(event.target.value as ExampleObservation["id"])}
                    className="input min-w-0 w-44 text-[12.5px]"
                  >
                    {OBSERVATIONS.map((candidate) => (
                      <option key={candidate.id} value={candidate.id}>
                        {candidate.dateLabel}
                      </option>
                    ))}
                  </select>
                  </div>
                  <div className="flex min-w-0 shrink-0 items-center gap-2">
                  <span aria-hidden="true" className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-sunk text-[11px] font-bold">B</span>
                  <label className="sr-only" htmlFor="example-swipe-observation-b">B 관측 선택</label>
                  <select
                    id="example-swipe-observation-b"
                    value={observationB.id}
                    onChange={(event) => setSideBObservation(event.target.value as ExampleObservation["id"])}
                    className="input min-w-0 w-44 text-[12.5px]"
                  >
                    {OBSERVATIONS.map((candidate) => (
                      <option key={candidate.id} value={candidate.id}>
                        {candidate.dateLabel}
                      </option>
                    ))}
                  </select>
                  </div>
                  <div className="flex shrink-0 gap-1" role="group" aria-label="겹쳐 보기 층 선택">
                    {(["ortho", "dsm"] as const).map((candidate) => (
                      <button
                        key={candidate}
                        type="button"
                        aria-pressed={swipeLayersMatch && layerA === candidate}
                        onClick={() => setBothLayers(candidate)}
                        className={`tap-target inline-flex items-center rounded-md px-3 py-1.5 text-[12.5px] break-keep ${swipeLayersMatch && layerA === candidate ? "bg-sunk font-bold" : "text-ink-2"}`}
                      >
                        {layerLabel(candidate)}
                      </button>
                    ))}
                  </div>
                </div>
                {!swipeLayersMatch ? (
                  <div className="flex min-w-0 flex-col items-start gap-2 rounded-lg border border-line bg-surface px-4 py-6" role="status">
                    <p className="break-words text-[13px] font-bold">두 칸의 층이 다릅니다</p>
                    <p className="text-[12px] leading-5 text-ink-2">
                      A는 {layerLabel(layerA)}, B는 {layerLabel(layerB)}입니다. 겹쳐 보기 전에 같은 층을
                      고르세요 — 날짜는 그대로 둡니다.
                    </p>
                    <p className="flex flex-wrap gap-2">
                      <button type="button" onClick={() => setBothLayers("ortho")} className="btn min-h-11">
                        둘 다 정사영상으로
                      </button>
                      <button type="button" onClick={() => setBothLayers("dsm")} className="btn min-h-11">
                        둘 다 DSM으로
                      </button>
                    </p>
                  </div>
                ) : (
                  <>
                    {swipeSameObservation && (
                      <p role="status" className="min-w-0 shrink-0 break-words text-[11.5px] text-ink-muted">
                        같은 관측을 두 번 선택했습니다. 같은 사진이 양쪽에 겹쳐 보입니다.
                      </p>
                    )}
                    <div className="flex min-w-0 flex-col lg:min-h-0 lg:flex-1">
                      <SpatialSwipeCompare
                        frameProps={{
                          ...swipeViewport.frameProps,
                          "aria-label": `밀어서 비교 · A ${observationA.dateLabel} · B ${observationB.dateLabel}. 직접 끌어서 보고, 휠·두 손가락·두 번 두드리기로 확대합니다. 경계 손잡이를 끌거나 선택한 뒤 방향키로 경계를 옮길 수 있습니다.`,
                        }}
                        contentRef={swipeViewport.contentProps.ref}
                        contentStyle={swipeViewport.contentProps.style}
                        aspectRatio="1100 / 985"
                        left={
                          /* eslint-disable-next-line @next/next/no-img-element */
                          <img
                            key={layerA === "ortho" ? observationA.orthoSrc : observationA.dsmSrc}
                            src={layerA === "ortho" ? observationA.orthoSrc : observationA.dsmSrc}
                            alt=""
                            aria-hidden="true"
                            className="block h-full w-full object-contain"
                            draggable={false}
                          />
                        }
                        right={
                          /* eslint-disable-next-line @next/next/no-img-element */
                          <img
                            key={layerB === "ortho" ? observationB.orthoSrc : observationB.dsmSrc}
                            src={layerB === "ortho" ? observationB.orthoSrc : observationB.dsmSrc}
                            alt=""
                            aria-hidden="true"
                            className="block h-full w-full object-contain"
                            draggable={false}
                          />
                        }
                        leftLabel={`A ${observationA.dateLabel}`}
                        rightLabel={`B ${observationB.dateLabel}`}
                        boundary={swipeBoundary}
                        onBoundaryChange={setSwipeBoundary}
                        resetControl={<ViewportResetButton onReset={swipeViewport.reset} />}
                      />
                    </div>
                    {swipeViewport.note && (
                      <p className="shrink-0 text-[12px] leading-5 text-ink-2" role="status">{swipeViewport.note}</p>
                    )}
                  </>
                )}
              </>
            ) : compareMode ? (
              <div className="grid min-w-0 gap-3 md:grid-cols-2 md:gap-0 md:divide-x md:divide-line lg:min-h-0 lg:flex-1">
                <ExamplePane side="A" observation={observationA} layer={layerA} onObservationChange={setSideAObservation} onLayerChange={setLayerA} />
                <ExamplePane side="B" observation={observationB} layer={layerB} onObservationChange={setSideBObservation} onLayerChange={setLayerB} />
              </div>
            ) : (
              <>
                <p className="min-w-0 shrink-0 break-words text-[11.5px] text-ink-muted">선택한 관측</p>
                <div className="min-w-0 lg:min-h-0 lg:flex-1">
                  <ExamplePane side="A" observation={observationA} layer={layerA} onObservationChange={setSideAObservation} onLayerChange={setLayerA} />
                </div>
              </>
            )}
            <div className="flex min-w-0 shrink-0 flex-wrap items-center gap-x-3 gap-y-1">
              <p className="text-[11.5px] leading-5 text-ink-muted">{swipeMode ? "표시용 겹쳐 보기 · 정량 비교 아님" : "독립 보기 · 정량 비교 아님"}</p>
              <p className="text-[11.5px] leading-5 text-ink-2">
                출처 · {SOURCE_LINE}{" "}
                <a className="tap-target underline" href={LICENSE_HREF} target="_blank" rel="noreferrer">
                  라이선스 보기
                </a>
              </p>
              <details className="text-[12px] text-ink-2">
                <summary className="tap-target cursor-pointer font-semibold">조작 안내</summary>
                <ul className="mt-1 flex list-disc flex-col gap-1 pl-5 leading-5">
                  <li>마우스·펜·한 손가락으로 끌면 그림이 따라옵니다.</li>
                  <li>휠·두 손가락·두 번 두드리기로 누른 자리부터 확대합니다.</li>
                  <li>그림을 선택한 뒤 방향키·+ −·Home 키를 쓸 수 있습니다.</li>
                  <li>화면 확대·이동은 표시용이며 측정값이 아닙니다.</li>
                </ul>
              </details>
            </div>
          </section>
        }
        inspector={
          <>
            <div className="flex min-w-0 items-center justify-between gap-2">
              <h3 className="min-w-0 break-words text-[13px] font-bold">예시 화면 정보</h3>
              <button type="button" onClick={() => setInfoOpen(false)} className="tap-target shrink-0 text-[12px] underline text-ink-2 xl:hidden">
                닫기
              </button>
            </div>
            <section aria-label="예시 출처와 한계" className="rounded-lg border border-line bg-surface p-3">
              <h4 className="text-[13px] font-bold">출처와 라이선스</h4>
              <p className="mt-1 text-[12px] leading-5 text-ink-2">
                공개 해안 관측 · 화면 구성 예시 — 건설 현장이나 등록 현장의 자료가 아니며,
                등록·검사·분석 기록과 묶이지 않습니다.
              </p>
              <p className="mt-1 text-[12px] leading-5 text-ink-2">{SOURCE_LINE}</p>
              <p className="mt-1 text-[12px] leading-5 text-ink-2">
                <a className="tap-target underline" href={LICENSE_HREF} target="_blank" rel="noreferrer">
                  CC BY 4.0 라이선스 보기
                </a>
              </p>
              <p className="mt-1 text-[11.5px] leading-5 text-ink-muted">
                날짜는 발행처 표기일이며 정확한 시각·측지 검증이 없습니다. 보기용 크롭은
                화면 맞춤용 파생이며 등록 이행·검사·분석 근거가 아닙니다.
              </p>
            </section>
            <details className="rounded-lg border border-line bg-surface p-3">
              <summary className="tap-target cursor-pointer text-[13px] font-bold">이 화면에서 하지 않는 것</summary>
              <ul className="mt-1 flex list-disc flex-col gap-1 pl-5 text-[12px] leading-5 text-ink-2">
                <li>수치·면적·물량 계산과 높이 비교를 하지 않습니다.</li>
                <li>두 칸의 겹쳐 맞춤·같은 색 눈금·정합 판정을 하지 않습니다.</li>
                <li>분석 결과 레이어를 두지 않습니다.</li>
                <li>이 예시에서는 등록·준비·검사를 만들 수 없습니다. 자료 등록은 실제 현장의 자료 화면에서 합니다.</li>
              </ul>
            </details>
          </>
        }
        inspectorOpen={infoOpen}
        onCloseInspector={() => setInfoOpen(false)}
        inspectorId="design-example-info"
        inspectorLabel="예시 화면 정보"
      />
    </div>
  );
}
