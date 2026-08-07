import Link from "next/link";

import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError } from "@/lib/core-api/labels";
import { listMissions } from "@/lib/core-api/missions";
import { listDefectCandidates } from "@/lib/core-api/phase34";
import { formatRatioPercent } from "@/lib/core-api/phase34-labels";
import type { DefectCandidateListView, MissionRecordResponse } from "@/lib/core-api/types";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";

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
 * 자산·시설물 — Phase 4 표면 결함(균열) 후보 (PRD §25 Phase 4, MODEL-P4-001).
 *
 * 결함 후보는 **임무 단위**로 쌓인다(어느 비행에서 찍은 사진인가). 그래서 이 화면은
 * 임무를 고르는 것으로 시작한다 — 현장 단위 집계는 여러 임무를 가로지르는 별도
 * 데이터모델 결정이 필요해서 지금 만들지 않는다.
 *
 * 후보 0건은 "아직 안 돌았다"와 "돌렸는데 결함이 없다"를 구분하지 않는다 — 서버
 * 계약이 그 둘을 구분하지 않으므로(그 구분은 처리 작업 상태가 답한다) 화면도
 * 구분하는 척하지 않는다.
 */
export default async function AssetsPage({
  searchParams,
}: {
  searchParams: Promise<{ missionId?: string }>;
}) {
  const { missionId } = await searchParams;
  const missions = await fetchMissions();

  if (!missionId) {
    return (
      <div className="flex flex-col gap-4 p-4 sm:p-5">
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          결함 후보는 임무 단위로 쌓입니다. 확인할 임무를 고르세요.
        </p>
        {missions.length === 0 ? (
          <EmptyState
            title="발급된 임무가 없습니다"
            description="임무를 발급하고 비행·처리가 끝나면 그 임무의 결함 후보를 여기서 볼 수 있습니다."
            action={{ label: "임무 목록", href: "/missions" }}
          />
        ) : (
          <ul className="flex flex-col gap-2">
            {missions.map((mission) => (
              <li key={mission.missionId}>
                <Link
                  href={`/assets?missionId=${encodeURIComponent(mission.missionId)}`}
                  className="block rounded-lg border border-neutral-200 px-3 py-2 text-sm hover:bg-neutral-50 dark:border-neutral-800 dark:hover:bg-neutral-900"
                >
                  <span className="font-medium">{mission.missionId}</span>
                  <span className="ml-2 text-neutral-500">{mission.siteId}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

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

  return (
    <div className="flex flex-col gap-4 p-4 sm:p-5">
      <section className="rounded-lg border border-neutral-200 p-4 dark:border-neutral-800">
        <h2 className="text-sm font-semibold">{view.missionId}</h2>
        <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
          결함 후보 {view.candidateCount}건 · 사진 {view.sourceMediaIds.length}장
        </p>
        <Link href="/assets" className="mt-2 inline-block text-sm text-blue-600 hover:underline">
          다른 임무 선택
        </Link>
      </section>

      {view.candidateCount === 0 ? (
        <EmptyState
          title="이 임무의 결함 후보가 없습니다"
          description="탐지가 아직 실행되지 않았거나, 실행됐지만 후보가 나오지 않았습니다. 이 화면은 그 둘을 구분하지 않습니다 — 처리 작업 상태가 답합니다."
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[40rem] text-left text-sm">
            <thead className="border-b border-neutral-200 text-xs uppercase text-neutral-500 dark:border-neutral-800">
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
                  className="border-b border-neutral-100 dark:border-neutral-900"
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
