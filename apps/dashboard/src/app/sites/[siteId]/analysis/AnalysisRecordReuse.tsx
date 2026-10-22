import Link from "next/link";

import type { AnalysisEvidencePage, AnalysisView } from "@/lib/core-api/analysis";
import { formatKoreanDateTime } from "@/lib/datetime";

const NO_EVIDENCE: readonly AnalysisEvidencePage[] = [];

/** Existing authoritative record only: no fetch, calculation, suitability or access grant. */
export function AnalysisRecordReuse({
  record,
  evidencePages = NO_EVIDENCE,
  inputLabels,
}: {
  record: AnalysisView;
  evidencePages?: readonly AnalysisEvidencePage[];
  inputLabels?: { baseline?: string; current?: string };
}) {
  const site = encodeURIComponent(record.siteId);
  const id = encodeURIComponent(record.analysisId);
  const query = new URLSearchParams({ workAreaId: record.workAreaId, analysisId: record.analysisId });
  const recordHref = `/sites/${site}/analysis?${query.toString()}`;
  const apiPath = `/v2/sites/${site}/analyses/${id}`;
  // Partial or stale evidence pages must not be silently mixed with this record.
  const evidenceMatches = evidencePages.length > 0 && evidencePages.every((page) =>
    page.analysisId === record.analysisId && page.evidenceRevision === record.evidenceRevision
    && page.evidenceDigest === record.evidenceDigest);
  const calculationItems = evidenceMatches
    ? evidencePages.flatMap((page) => page.items).filter((item) => item.kind === "CALCULATION_IDENTITY")
    : [];
  const calculation = calculationItems.length === 1 ? calculationItems[0]!.calculation : null;
  const inputs = [
    { label: "기준 입력", title: inputLabels?.baseline, selector: record.baseline },
    { label: "현재 입력", title: inputLabels?.current, selector: record.current },
  ];

  return <details className="rounded-lg border border-line bg-surface px-4 py-3 text-[12px] leading-5 text-ink-2">
    <summary className="tap-target cursor-pointer font-semibold text-ink-1">결과 계보·재사용 정보</summary>
    <div className="mt-3 flex min-w-0 flex-col gap-3">
      <p>이 기록의 원래 입력과 결과를 확인합니다. 탐색 중인 자료나 화면 범위로 계산 입력을 바꾸지 않습니다.</p>
      <dl className="grid gap-3 sm:grid-cols-2">
        {inputs.map(({ label, title, selector }) => <div key={label} className="min-w-0">
          <dt className="font-semibold text-ink-1">{label}</dt>
          {title && <dd className="break-words">{title}</dd>}
          <dd>등록 버전 {selector.revision}</dd>
          <dd className="break-all">작업 기록 · <code>{selector.workOrderId}</code></dd>
          <dd className="break-all">제출 묶음 · <code>{selector.submissionRef}</code></dd>
        </div>)}
        <div className="min-w-0"><dt className="text-ink-muted">작업구역</dt><dd className="break-all"><code>{record.workAreaId}</code></dd></div>
        <div className="min-w-0"><dt className="text-ink-muted">요청 기록 시각</dt><dd>{formatKoreanDateTime(record.createdAt, { dateStyle: "medium", timeStyle: "short" })}</dd></div>
        <div className="min-w-0"><dt className="text-ink-muted">분석 기록 ID</dt><dd className="break-all"><code>{record.analysisId}</code></dd></div>
        <div className="min-w-0"><dt className="text-ink-muted">결과 ID</dt><dd className="break-all">{record.result ? <code>{record.result.resultId}</code> : "기록된 계산 결과 없음"}</dd></div>
        {record.result && <>
          <div className="min-w-0"><dt className="text-ink-muted">계산 시각</dt><dd>{formatKoreanDateTime(record.result.computedAt, { dateStyle: "medium", timeStyle: "short" })}</dd></div>
          <div className="min-w-0"><dt className="text-ink-muted">보고서 확인값</dt><dd className="break-all"><code>{record.result.reportDigest}</code></dd></div>
          <div className="min-w-0"><dt className="text-ink-muted">수치 결과 식별 확인값</dt><dd className="break-all"><code>{record.result.numericResultIdentityDigest}</code></dd></div>
        </>}
        <div className="min-w-0"><dt className="text-ink-muted">현재 근거 개정</dt><dd>{record.evidenceRevision}</dd></div>
        <div className="min-w-0"><dt className="text-ink-muted">현재 근거 목록 확인값</dt><dd className="break-all"><code>{record.evidenceDigest}</code></dd></div>
      </dl>

      {calculation ? <details className="border-t border-line pt-2">
        <summary className="tap-target cursor-pointer font-semibold">계산 조건·실행 버전</summary>
        <dl className="mt-2 grid gap-3 sm:grid-cols-2">
          <div className="min-w-0"><dt className="text-ink-muted">계산 기록</dt><dd className="break-all"><code>{calculation.calculationId}</code></dd></div>
          <div className="min-w-0"><dt className="text-ink-muted">작업구역 정의 확인값</dt><dd className="break-all"><code>{calculation.workAreaDefinitionDigest}</code></dd></div>
          <div className="min-w-0"><dt className="text-ink-muted">계산 프로필</dt><dd className="break-all"><code>{calculation.policy.profileId}</code></dd></div>
          <div className="min-w-0"><dt className="text-ink-muted">프로필 확인값</dt><dd className="break-all"><code>{calculation.policy.profileDigest}</code></dd></div>
          <div className="min-w-0"><dt className="text-ink-muted">적용 정책</dt><dd className="break-all"><code>{calculation.policy.policyId}</code> · 버전 {calculation.policy.version}</dd></div>
          <div className="min-w-0"><dt className="text-ink-muted">정책 확인값</dt><dd className="break-all"><code>{calculation.policy.policyDigest}</code></dd></div>
          <div className="min-w-0"><dt className="text-ink-muted">기준 입력 확인값</dt><dd className="break-all"><code>{calculation.baselineInputDigest}</code></dd></div>
          <div className="min-w-0"><dt className="text-ink-muted">현재 입력 확인값</dt><dd className="break-all"><code>{calculation.currentInputDigest}</code></dd></div>
          <div className="min-w-0"><dt className="text-ink-muted">연산 설정 확인값</dt><dd className="break-all"><code>{calculation.policy.configDigest}</code></dd></div>
          <div className="min-w-0"><dt className="text-ink-muted">계산 알고리즘 확인값</dt><dd className="break-all"><code>{calculation.policy.algorithmDigest}</code></dd></div>
          <div className="min-w-0"><dt className="text-ink-muted">실행 이미지 버전</dt><dd><code>{calculation.runtime.runtimeImageVersion}</code></dd></div>
          <div className="min-w-0"><dt className="text-ink-muted">실행 이미지 확인값</dt><dd className="break-all"><code>{calculation.runtime.runtimeImageOciDigest}</code></dd></div>
          <div className="min-w-0"><dt className="text-ink-muted">의존성 버전 확인값</dt><dd className="break-all"><code>{calculation.runtime.dependencyLockDigest}</code></dd></div>
        </dl>
      </details> : <p className="border-t border-line pt-2">
        {evidencePages.length > 0 && !evidenceMatches
          ? "불러온 근거의 개정이 현재 기록과 달라 계산 조건을 합쳐 표시하지 않았습니다. 근거를 다시 확인하세요."
          : "이 기록에 맞는 계산 조건을 아직 불러오지 못했습니다. 이 화면의 ‘근거 확인’에서 확인하세요."}
      </p>}

      <div className="border-t border-line pt-2">
        <Link href={recordHref} className="tap-target inline-flex font-semibold text-ink-1 underline">이 분석 기록의 링크 열기</Link>
        <p className="mt-1">링크 주소를 복사해 같은 기록을 다시 열 수 있습니다. 링크 자체에 열람 권한은 없으며 로그인과 현장 접근 권한을 다시 확인합니다.</p>
        <p className="mt-1">기록된 계산 결과와 현재 활용 가능 여부는 별개입니다. 이후 근거 평가·검토 상태는 바뀔 수 있으며, 이 정보는 정확도·측량·정산 승인이 아닙니다.</p>
      </div>
      <details className="border-t border-line pt-2">
        <summary className="tap-target cursor-pointer font-semibold">API·MCP 조회 참고</summary>
        <p className="mt-2">아래는 같은 분석 기록을 가리키는 기존 Core API 경로입니다. Console 로그인 세션을 외부 도구의 인증으로 대신 쓰지 않습니다. 서버 주소·API 인증·현장 권한은 별도로 설정해야 합니다.</p>
        <p className="mt-2 break-all"><code>GET {apiPath}</code></p>
        <p className="mt-1 break-all"><code>GET {apiPath}/evidence</code></p>
        <p className="mt-2">기존 로컬 stdio MCP 어댑터의 조회 도구에 사용할 식별 정보:</p>
        <p className="mt-1 break-all"><code>ksi_get_analysis</code> · <code>{JSON.stringify({ siteId: record.siteId, analysisId: record.analysisId })}</code></p>
        <p className="mt-2">MCP는 전용 신원과 별도 현장 AI 반출 동의를 요구합니다. 이 화면은 연결·반출 동의를 설정하거나 허용 여부를 판정하지 않으며, 외부 클라이언트의 연결 성공을 보증하지 않습니다.</p>
      </details>
    </div>
  </details>;
}
