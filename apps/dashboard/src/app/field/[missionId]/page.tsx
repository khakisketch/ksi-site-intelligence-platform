import type { ReactNode } from "react";

import Link from "next/link";
import { notFound } from "next/navigation";

import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError, MISSION_TYPE_LABEL } from "@/lib/core-api/labels";
import { getCoverageReport, getMission, getMissionExecution } from "@/lib/core-api/missions";
import { listProcessingJobs } from "@/lib/core-api/processing-jobs";
import { getSite } from "@/lib/core-api/sites";
import { getSourceMediaBundle } from "@/lib/core-api/source-media";
import { formatKoreanDateTime } from "@/lib/datetime";
import { ErrorState } from "@/components/ui/ErrorState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { KmzDownloadButton } from "@/components/missions/KmzDownloadButton";
import { ManualDispatchButton } from "@/components/missions/ManualDispatchButton";
import { SourceUploadPanel } from "@/components/missions/SourceUploadPanel";
import type { CoverageReportView, SourceMediaBundleView } from "@/lib/core-api/types";

import { formatRatio } from "../../missions/format";
import { FieldBlocked, FieldHeader, FieldInlineLogin } from "../FieldShell";
import { PilotBridgeProbe } from "../PilotBridgeProbe";
import {
  deriveFieldStages,
  deriveFlightStart,
  type FieldCoverageInput,
  type FieldMediaInput,
  type FieldStage,
} from "../field-stages";
import { resolveFieldSession } from "../resolve-session";

// 단일 임무 현장 화면 — 4단(경로 확보 / 비행 / 사진 회수 / 결과).
//
// ── 이 화면의 설계 판단 하나 ────────────────────────────────────────────────
// **수동 컨트롤을 실패 상태 뒤에 숨기지 않는다.** 자동 경로가 깨지는 상황은 정의상
// 통신 두절·장비 고장이고, 그때 "실패를 감지해야 나타나는 버튼"은 나타나지 않는다.
// 그래서 KMZ 다운로드·사진 업로드는 자동 상태와 무관하게 **언제나 자리에 있다.**
// 자동이 정상 진행 중일 때는 흐리게(opacity) 물러나되 누를 수는 있게 둔다 —
// pointer-events 를 끄면 그건 숨긴 것과 같다.
//
// 신규 서버 API 0건(ADR-KSI-017). 조회는 전부 임무 상세 화면이 쓰던 것 그대로다.

export const metadata = { title: "현장 임무 · KSI" };

/** 커버리지 조회 결과를 4단 도출이 받는 모양으로 좁힌다(에러 객체를 순수 로직에 넣지 않는다). */
async function fetchCoverage(
  missionId: string,
): Promise<{ input: FieldCoverageInput; report: CoverageReportView | null }> {
  try {
    const report = await getCoverageReport(missionId);
    return {
      input: {
        kind: "reported",
        completionState: report.latest.summary.completionState,
        recoveryRecommended: report.recoveryRecommended,
      },
      report,
    };
  } catch (error) {
    // 404 는 "아직 보고 없음"이지 오류가 아니다(임무 상세 화면과 같은 규약).
    if (error instanceof CoreApiError && error.status === 404) {
      return { input: { kind: "not-reported" }, report: null };
    }
    if (error instanceof CoreApiError) return { input: { kind: "error" }, report: null };
    throw error;
  }
}

/**
 * 사진 묶음 조회 결과를 4단 도출이 받는 모양으로 좁힌다(fetchCoverage 와 같은 패턴).
 *
 * `.catch(() => null)` 로 실패를 삼키지 않는다 — "등록된 적 없음"(404)과
 * "조회 실패"(그 외 오류)를 갈라야 mediaStage 가 그 둘을 다른 문구·톤으로 보여줄 수
 * 있다. 뭉개면 Core 가 잠깐 불안정한 순간에도 이미 올린 사진이 "없다"고 나온다.
 */
async function fetchMediaBundle(
  missionId: string,
): Promise<{ input: FieldMediaInput; bundle: SourceMediaBundleView | null }> {
  try {
    const bundle = await getSourceMediaBundle(missionId);
    return { input: { kind: "registered", bundle }, bundle };
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) {
      return { input: { kind: "not-registered" }, bundle: null };
    }
    if (error instanceof CoreApiError) return { input: { kind: "error" }, bundle: null };
    throw error;
  }
}

export default async function FieldMissionPage({
  params,
}: {
  params: Promise<{ missionId: string }>;
}) {
  const { missionId } = await params;

  const session = await resolveFieldSession();
  if (session.kind === "blocked") {
    // 로그인 후·재시도 후 **이 임무 화면으로** 돌아온다 — 목록에서 다시 찾게 하지 않는다.
    const next = `/field/${encodeURIComponent(missionId)}`;
    return session.verdict.kind === "login" ? (
      <FieldInlineLogin next={next} notice={session.verdict.notice} />
    ) : (
      <FieldBlocked message={session.verdict.message} retryHref={next} />
    );
  }

  let mission;
  try {
    mission = await getMission(missionId);
  } catch (error) {
    if (error instanceof CoreApiError) {
      if (error.status === 404) notFound();
      return (
        <div className="field-controls flex flex-col">
          <FieldHeader principal={session.principal} />
          <div className="flex flex-col gap-4 p-4">
            <BackToList />
            <ErrorState
              message={humanizeApiError(error.code, error.status, error.serverMessage)}
              detail={error.serverMessage}
              retryable
            />
          </div>
        </div>
      );
    }
    throw error;
  }

  // 나머지는 전부 부가 정보다 — 하나가 실패해도 화면과 수동 경로는 살아 있어야 한다
  // (현장에서 화면이 통째로 죽는 것이 이 제품에서 가장 나쁜 실패다).
  const [site, execution, coverage, media, jobs] = await Promise.all([
    getSite(mission.siteId).catch(() => null),
    getMissionExecution(mission.missionId).catch(() => null),
    fetchCoverage(mission.missionId),
    fetchMediaBundle(mission.missionId),
    listProcessingJobs(mission.missionId)
      .then((r) => r.jobs)
      .catch(() => []),
  ]);

  const stages = deriveFieldStages({
    artifactKind: mission.artifactKind,
    execution,
    media: media.input,
    coverage: coverage.input,
  });
  const flightStart = deriveFlightStart({ execution });
  const latestJob = [...jobs].sort((a, b) => b.issuedAt.localeCompare(a.issuedAt))[0] ?? null;
  const canIssue = session.principal.permissions.includes("MISSIONS_ISSUE");
  // 자동 전달이 확인된 동안에는 수동 이관을 한 걸음 물린다 — 지우지는 않는다.
  const routeHandledAutomatically =
    execution !== null && execution.status !== "ISSUED" && execution.status !== "CANCELLED";

  return (
    // field-controls — 재사용 컴포넌트(KmzDownloadButton·SourceUploadPanel)의 버튼까지
    // 현장 치수(44px)로 올린다. 그 컴포넌트들은 className 을 안에서 고정하므로 밖에서
    // 붙일 수 없다(globals.css 의 같은 이름 규칙 주석).
    <div className="field-controls flex flex-col">
      <FieldHeader principal={session.principal}>
        <div className="flex flex-col gap-1">
          <h1 className="text-[17px] font-bold tracking-tight break-keep">
            {MISSION_TYPE_LABEL[mission.missionType]} · {site ? site.name : mission.siteId}
          </h1>
          <p className="num text-[12px] break-token text-ink-muted">
            {formatKoreanDateTime(mission.issuedAt, { dateStyle: "medium", timeStyle: "short" })} 발급
            · {mission.missionId}
          </p>
        </div>
      </FieldHeader>

      <div className="flex flex-col gap-4 p-4">
        <BackToList />

        <StageCard index={1} stage={stages[0]}>
          {/* KMZ 다운로드·수동 이관 신고는 자동 전달 여부와 무관하게 항상 여기 있다. */}
          <div className={`flex flex-col gap-4 ${routeHandledAutomatically ? "opacity-60" : ""}`}>
            <KmzDownloadButton
              missionId={mission.missionId}
              hasKmz={mission.artifactKind === "pair"}
            />
            <ManualDispatchButton
              missionId={mission.missionId}
              canDeclare={canIssue}
              executionStatus={execution?.status ?? null}
            />
          </div>
        </StageCard>

        <StageCard index={2} stage={stages[1]}>
          <div className="flex flex-col items-start gap-1.5">
            {/* disabled 는 `!flightStart.enabled` 로 읽는다 — `deriveFlightStart` 가
                항상 false 를 내는 지금은 하드코딩과 같은 결과지만, 이 버튼이 그
                값을 실제로 읽는다는 계약을 코드에 남긴다(field-stages.test.ts
                cross-check 참고). */}
            <button
              type="button"
              disabled={!flightStart.enabled}
              className="btn btn-field btn-primary"
            >
              임무 시작
            </button>
            {/* 비활성 버튼에 title 툴팁을 다는 대신 문장을 상시 노출한다 — 터치
                기기에는 hover 가 없어 툴팁은 아무에게도 보이지 않는다. */}
            <p className="text-[12.5px] break-keep text-ink-2">{flightStart.reason}</p>
          </div>
        </StageCard>

        <StageCard index={3} stage={stages[2]}>
          {/* 자동 회수(매니폴드 워커 → PSDK 어댑터) 진행 표시는 지금 데이터 원천이
              없다 — 워커가 아직 배선되지 않았고 서버에도 그 수치를 낼 표면이 없다.
              값을 지어내는 대신 미구현임을 그대로 말한다(다음 단계에서 배선되면
              여기가 실제 진행률로 바뀐다). */}
          <p className="text-[12px] break-keep text-ink-muted">
            자동 회수 상태(장수·잔여 스풀 용량)는 아직 표시되지 않습니다 — 다음
            단계에서 추가할 예정입니다.
          </p>
          <SourceUploadPanel
            missionId={mission.missionId}
            canIssue={canIssue}
            initialBundle={media.bundle}
            initialJob={latestJob ? { jobId: latestJob.jobId, status: latestJob.status } : null}
            // 비교 리포트 유무는 현장에서 할 일이 아니다(사무실 화면의 판단이다).
            // false 로 두면 재구성 완료 직후 "아직 비교 리포트가 없다"는 안내가 뜨는데,
            // 현장에서는 그게 맞는 안내다 — 재구성은 방금 끝났고 비교는 아직이다.
            hasComparisonReport={false}
          />
        </StageCard>

        <StageCard index={4} stage={stages[3]}>
          {coverage.report && (
            <dl className="grid grid-cols-3 gap-2">
              <ResultTile label="필수 위험구역" value={coverage.report.latest.summary.mandatoryHazardRatio} />
              <ResultTile label="필수 자산" value={coverage.report.latest.summary.mandatoryAssetRatio} />
              <ResultTile label="접근가능 일반영역" value={coverage.report.latest.summary.accessibleGeneralRatio} />
            </dl>
          )}
          <Link
            href={`/missions/${encodeURIComponent(mission.missionId)}`}
            className="btn btn-field w-fit"
          >
            자세한 결과 보기
          </Link>
        </StageCard>

        <PilotBridgeProbe />
      </div>
    </div>
  );
}

/**
 * 4단 각각의 카드 — 자동 상태(배지+문장)와 수동 경로(문장+컨트롤)를 **나란히** 둔다.
 *
 * 자동/수동을 탭이나 아코디언으로 가르지 않는다. 현장에서 필요한 판단은 "자동이
 * 어디까지 갔나 / 지금 내가 뭘 해야 하나" 둘 동시이고, 하나를 접으면 그 판단이
 * 두 동작으로 늘어난다.
 */
function StageCard({
  index,
  stage,
  children,
}: {
  index: number;
  stage: FieldStage;
  children?: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="num text-[11px] font-bold text-ink-muted">{index}</span>
        <h2 className="text-[15px] font-bold tracking-tight break-keep">{stage.title}</h2>
        <StatusBadge label={stage.auto.label} tone={stage.auto.tone} />
        {/* 배지가 대표하는 사실이 언제 성립했는지 — 라벨만 내고 시각을 버리면
            운영자는 "지금 막" 벌어진 일인지 몇 시간 전 일인지 구분할 수 없다. */}
        {stage.auto.updatedAt && (
          <span className="num text-[11px] break-keep text-ink-muted">
            [{stage.auto.label} {formatKoreanDateTime(stage.auto.updatedAt, { timeStyle: "short" })}]
          </span>
        )}
      </div>
      <p className="text-[13px] break-keep text-ink-2">{stage.auto.detail}</p>
      {stage.manual && (
        <p className="border-t border-line pt-3 text-[13px] break-keep text-ink-2">
          <span className="font-semibold text-ink-1">수동 경로</span> · {stage.manual}
        </p>
      )}
      {children}
    </section>
  );
}

function ResultTile({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-lg border border-line bg-sunk p-3">
      <dt className="text-[11px] font-semibold break-keep text-ink-2">{label}</dt>
      {/* 비율 포맷은 임무 화면과 같은 함수를 쓴다 — 같은 수치가 화면마다 다른
          자릿수로 보이면 운영자는 둘이 다른 값이라고 읽는다. */}
      <dd className="num text-[19px] leading-tight font-bold tracking-tight">{formatRatio(value)}</dd>
    </div>
  );
}

function BackToList() {
  return (
    <Link href="/field" className="btn btn-field w-fit">
      ← 오늘 임무
    </Link>
  );
}
