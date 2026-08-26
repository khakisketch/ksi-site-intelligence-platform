import Link from "next/link";

import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError } from "@/lib/core-api/labels";
import { listMissions } from "@/lib/core-api/missions";
import { getSourceMediaView, listDefectCandidates } from "@/lib/core-api/phase34";
import { formatRatioPercent } from "@/lib/core-api/phase34-labels";
import type {
  DefectCandidateListView,
  MissionRecordResponse,
  SourceMediaViewResponse,
} from "@/lib/core-api/types";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { SiteAreaPicker } from "@/components/site/SiteAreaPicker";
import { listSitesCached } from "@/lib/core-api/cached";

import { DefectOverlay } from "./DefectOverlay";

type Result =
  | { view: DefectCandidateListView; error: null }
  | { view: null; error: CoreApiError };

async function fetchDefects(missionId: string): Promise<Result> {
  try {
    return { view: await listDefectCandidates(missionId), error: null };
  } catch (error) {
    if (error instanceof CoreApiError) return { view: null, error };
    throw error;
  }
}

async function fetchMissions(): Promise<MissionRecordResponse[]> {
  // 임무 목록은 진입 보조다 — 실패해도 화면 자체는 서야 하므로 빈 목록으로 내려간다.
  try {
    return await listMissions();
  } catch {
    return [];
  }
}

/**
 * 사진 열람 URL — 실패해도 표는 보여야 하므로 null 로 내려간다.
 *
 * URL 발급 실패(스토리지 장애 503)와 사진 미업로드는 다른 사실이지만, 이 화면에서
 * 할 수 있는 일은 "오버레이 대신 표만 보여준다"로 같다. 그 구분은 오버레이 안에서
 * 이미지 로드 실패로 드러난다(DefectOverlay).
 */
async function fetchPhoto(
  missionId: string,
  mediaId: string,
): Promise<SourceMediaViewResponse | null> {
  try {
    return await getSourceMediaView(missionId, mediaId);
  } catch {
    return null;
  }
}

/**
 * 결함 후보 — Phase 4 표면 결함(균열) 후보 (PRD §25 Phase 4, MODEL-P4-001).
 *
 * PRD §7.1 의 슬롯 이름은 "자산·시설물"이지만, 이 화면이 실제로 보여주는 것은 임무
 * 사진에서 나온 결함 후보뿐이다(자산 엔티티 0개) — 이름을 내용에 맞췄다(2026-08-17).
 *
 * 결함 후보는 **임무 단위**로 쌓인다(어느 비행에서 찍은 사진인가). 그래서 이 화면은
 * 임무를 고르는 것으로 시작하고, 그 안에서 사진을 골라 폴리곤을 원본 위에 겹친다.
 * 현장 단위 집계는 여러 임무를 가로지르는 별도 데이터모델 결정이 필요해서 지금
 * 만들지 않는다.
 *
 * 후보 0건은 "아직 안 돌았다"와 "돌렸는데 결함이 없다"를 구분하지 않는다 — 서버
 * 계약이 그 둘을 구분하지 않으므로(그 구분은 처리 작업 상태가 답한다) 화면도
 * 구분하는 척하지 않는다.
 */
export default async function AssetsPage({
  searchParams,
}: {
  searchParams: Promise<{ missionId?: string; mediaId?: string }>;
}) {
  const { missionId, mediaId } = await searchParams;
  const [missions, sites] = await Promise.all([
    fetchMissions(),
    listSitesCached().catch(() => []),
  ]);

  if (!missionId) {
    return (
      <SiteAreaPicker
        sites={sites}
        title="현장 확인 항목"
        description="결함 후보와 관측 근거는 현장 맥락에서 검토합니다. 확인할 현장을 선택하세요."
        section="review-items"
      />
    );
  }

  const currentMission = missions.find((mission) => mission.missionId === missionId) ?? null;
  const currentSite = currentMission
    ? sites.find((site) => site.siteId === currentMission.siteId) ?? null
    : null;

  const { view, error } = await fetchDefects(missionId);
  if (error) {
    return (
      <div className="flex flex-col gap-4 p-4 sm:p-5">
        <ErrorState
          message={humanizeApiError(error.code, error.status, error.serverMessage)}
          detail={error.serverMessage}
        />
      </div>
    );
  }

  // 사진을 안 고르면 첫 장을 연다 — 후보가 걸린 사진만 목록에 있으므로 첫 장도
  // 반드시 무언가를 보여준다(빈 화면으로 시작하지 않는다).
  const selectedMediaId = mediaId ?? view.sourceMediaIds[0];
  const selectedCandidates = view.candidates
    .filter((item) => item.candidate.sourceMediaId === selectedMediaId)
    .map((item) => item.candidate);
  const photo = selectedMediaId ? await fetchPhoto(view.missionId, selectedMediaId) : null;

  return (
    <div className="flex flex-col gap-4 p-4 sm:p-5">
      <section className="rounded-lg border border-line p-4">
        <h2 className="text-sm font-semibold">{currentSite?.name ?? "임무 근거"}</h2>
        <p className="mt-1 text-sm text-ink-2">
          결함 후보 {view.candidateCount}건 · 사진 {view.sourceMediaIds.length}장
        </p>
        <div className="mt-2 flex flex-wrap gap-x-4">
          {currentMission && (
            <Link
              href={`/sites/${encodeURIComponent(currentMission.siteId)}?section=review-items`}
              className="tap-target inline-flex items-center text-sm text-accent-text hover:underline"
            >
              현장 확인 항목으로
            </Link>
          )}
          <Link href="/assets" className="tap-target inline-flex items-center text-sm text-accent-text hover:underline">
            다른 현장 선택
          </Link>
        </div>
      </section>

      {view.sourceMediaIds.length > 0 && (
        <nav className="flex flex-wrap gap-2" aria-label="사진 선택">
          {view.sourceMediaIds.map((id) => (
            <Link
              key={id}
              href={`/assets?missionId=${encodeURIComponent(view.missionId)}&mediaId=${encodeURIComponent(id)}`}
              className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                // 선택 상태 = 액센트(무채색). 안전 상태색을 쓰지 않는다 —
                // 이 칩은 "지금 보고 있는 사진"이지 위험도가 아니다.
                id === selectedMediaId
                  ? "border-accent bg-accent text-accent-on"
                  : "border-line-strong hover:bg-sunk"
              }`}
            >
              {id}
            </Link>
          ))}
        </nav>
      )}

      {photo && selectedCandidates.length > 0 && (
        <DefectOverlay
          viewUrl={photo.viewUrl}
          width={photo.width}
          height={photo.height}
          candidates={selectedCandidates}
        />
      )}

      {view.candidateCount === 0 ? (
        <EmptyState
          title="이 임무의 결함 후보가 없습니다"
          description="탐지가 아직 실행되지 않았거나, 실행됐지만 후보가 나오지 않았습니다. 이 화면은 그 둘을 구분하지 않습니다 — 처리 작업 상태가 답합니다."
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[40rem] text-left text-sm">
            <thead className="border-b border-line text-xs uppercase text-ink-muted">
              <tr>
                <th className="px-3 py-2">후보 ID</th>
                <th className="px-3 py-2">사진</th>
                <th className="px-3 py-2">유형</th>
                <th className="px-3 py-2">신뢰도</th>
                <th className="px-3 py-2">면적(px²)</th>
                <th className="px-3 py-2">길이(px)</th>
              </tr>
            </thead>
            <tbody>
              {view.candidates.map(({ candidate }) => (
                <tr
                  key={candidate.defectCandidateId}
                  className="border-b border-line"
                >
                  <td className="px-3 py-2 font-mono text-xs">{candidate.defectCandidateId}</td>
                  <td className="px-3 py-2">{candidate.sourceMediaId}</td>
                  <td className="px-3 py-2">{candidate.defectType}</td>
                  <td className="px-3 py-2">{formatRatioPercent(candidate.confidence)}</td>
                  <td className="px-3 py-2">
                    {candidate.measurements?.areaPx2?.toFixed(0) ?? "—"}
                  </td>
                  <td className="px-3 py-2">
                    {candidate.measurements?.lengthPx?.toFixed(0) ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
