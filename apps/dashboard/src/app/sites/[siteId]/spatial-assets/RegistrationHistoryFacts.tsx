import {
  describeCaptureLine,
  describeProducerLine,
  describeRetentionLine,
} from "@/app/field/registration-language";
import { formatKoreanDateTime } from "@/lib/datetime";
import type { ValidatedRegistrationHistory } from "@/lib/registration-history";

/**
 * 선택한 자산의 제출서 등록 이력 — Core V3 선언 그대로 읽는다.
 *
 * - 촬영 날짜·제작자·보관·출처·내보내기는 제출자가 신고한 값이며, KSI가
 *   관측·검증한 사실이 아니다. 판정·측정·정확도 평가를 하지 않는다.
 * - 원자료 출처와 제출 산출물의 내보내기 도구는 분리해 표시한다.
 * - 출처 URI는 표시용 http(s) 검증분을 링크로만 두며, 자동 조회·이미지
 *   삽입을 하지 않는다. 전체 URI·확인값은 펼침 안에 둔다.
 */

function IntervalLine({ history }: { history: ValidatedRegistrationHistory }): string | null {
  return describeCaptureLine(
    {
      captureBasis: history.captureBasis,
      captureStartedAt: history.captureStartedAt,
      captureEndedAt: history.captureEndedAt,
      captureDate: history.captureDate,
    },
    (startedAt, endedAt) =>
      `${formatKoreanDateTime(startedAt, { dateStyle: "medium", timeStyle: "short" })} – ${formatKoreanDateTime(endedAt, { dateStyle: "medium", timeStyle: "short" })}`,
  );
}

export function RegistrationHistoryFacts({ history }: { history: ValidatedRegistrationHistory }) {
  const captureLine = IntervalLine({ history });
  const producerLine = describeProducerLine({
    producerKnowledge: history.producerKnowledge,
    softwareName: history.softwareName,
    softwareVersion: history.softwareVersion,
    sourceNote: history.sourceNote,
  });
  const retentionLine = describeRetentionLine({
    originalRetentionLocus: history.originalRetentionLocus,
    originalRetentionDetail: history.originalRetentionDetail,
  });
  return <section aria-label="등록 이력" className="rounded-lg border border-line bg-surface p-4">
    <h3 className="text-[14px] font-bold">등록 이력 (제출서 기준)</h3>
    <div className="mt-3 flex flex-col gap-2 text-[12.5px] leading-5 text-ink-2">
      {captureLine && <p>{captureLine}</p>}
      {producerLine && <p>{producerLine}</p>}
      {history.sourceNote && <p className="break-words">제작 참고: {history.sourceNote}</p>}
      {retentionLine && <p>{retentionLine}</p>}
    </div>

    {history.upstreamSource && <div className="mt-3 rounded-md border border-line bg-sunk/50 px-3 py-2">
      <h4 className="text-[12.5px] font-bold">원자료 출처 (제출서 신고)</h4>
      <p className="mt-1 text-[12px] leading-5 text-ink-2">공개 라이선스 신고: {history.upstreamSource.licenceDeclaration ?? "없음"}</p>
      <details className="mt-1 text-[12px] text-ink-2">
        <summary className="tap-target cursor-pointer font-semibold text-ink-muted">출처 원문 보기</summary>
        <div className="mt-1 flex flex-col gap-1 break-all border-t border-line pt-2">
          {history.upstreamSource.retrievalNote && <p className="whitespace-pre-wrap">입수 기록: {history.upstreamSource.retrievalNote}</p>}
          {history.upstreamSource.sourceUri
            ? <p>출처 주소 · <a href={history.upstreamSource.sourceUri} rel="noreferrer" className="text-accent-text underline">{history.upstreamSource.sourceUri}</a></p>
            : <p>출처 주소 미기재</p>}
          {history.upstreamSource.sourceSha256 && <p className="font-mono text-[11px]">출처 확인값(SHA-256) · {history.upstreamSource.sourceSha256}</p>}
        </div>
      </details>
      <p className="mt-1 text-[11.5px] leading-5 text-ink-muted">출처와 라이선스는 제출자가 신고한 내용이며, KSI 접근·사용 권한 부여와는 별개입니다.</p>
    </div>}

    {history.derivativeExport && <div className="mt-3 rounded-md border border-line bg-sunk/50 px-3 py-2">
      <h4 className="text-[12.5px] font-bold">제출 산출물 내보내기 (로컬 도구)</h4>
      <p className="mt-1 text-[12px] leading-5 text-ink-2">도구: {history.derivativeExport.toolName} {history.derivativeExport.toolVersion}</p>
      {history.derivativeExport.exportedAt && <p className="mt-1 text-[12px] leading-5 text-ink-2">내보내기 시각: {formatKoreanDateTime(history.derivativeExport.exportedAt, { dateStyle: "medium", timeStyle: "short" })}</p>}
      {history.derivativeExport.exportNote && <p className="mt-1 break-words text-[12px] leading-5 text-ink-2">내보내기 기록: {history.derivativeExport.exportNote}</p>}
      <details className="mt-1 text-[12px] text-ink-2">
        <summary className="tap-target cursor-pointer font-semibold text-ink-muted">설정 확인값 보기</summary>
        <div className="mt-1 border-t border-line pt-2">
          {history.derivativeExport.settingsDigest
            ? <p className="break-all font-mono text-[11px]">설정 확인값 · {history.derivativeExport.settingsDigest}</p>
            : <p>설정 확인값 미기재</p>}
        </div>
      </details>
      <p className="mt-1 text-[11.5px] leading-5 text-ink-muted">제출 파일을 내보낸 도구의 신고 기록입니다. 원자료의 재구성 소프트웨어나 KSI의 실행 사실을 뜻하지 않습니다.</p>
    </div>}

    <p className="mt-3 text-[11.5px] leading-5 text-ink-muted">위 날짜·출처·도구는 제출자가 신고한 값이며, KSI가 관측·검증한 사실이 아닙니다. 등록 이력 읽기입니다. 판정·측정·정확도 평가가 아닙니다.</p>
    <p className="mt-1 text-[11.5px] text-ink-muted">출처: 제출서 등록 버전 {history.revision} · {history.state === "SEALED" ? "봉인됨" : "등록됨"}</p>
  </section>;
}

export function RegistrationHistoryUnavailable() {
  return <p role="status" className="rounded-lg border border-line bg-sunk px-4 py-3 text-[12px] leading-5 text-ink-2">
    등록 이력(제출서)을 확인하지 못했습니다. 파일의 등록 정보는 그대로이며, 촬영 날짜·출처는 확인할 수 없습니다.
  </p>;
}
