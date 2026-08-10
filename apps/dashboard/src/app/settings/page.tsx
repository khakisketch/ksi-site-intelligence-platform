import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError } from "@/lib/core-api/labels";
import { listEquipmentSupport } from "@/lib/core-api/phase34";
import { SUPPORT_LEVEL_LABEL, SUPPORT_LEVEL_ORDER } from "@/lib/core-api/phase34-labels";
import type { EquipmentSupportListView, EquipmentSupportView } from "@/lib/core-api/types";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";

type Result =
  | { view: EquipmentSupportListView; error: null }
  | { view: null; error: CoreApiError };

// JSX 를 try/catch 안에서 만들지 않는다 — fetch 만 감싸고 렌더링은 결과로 분기한다
// (missions/page.tsx 관습).
async function fetchSupport(): Promise<Result> {
  try {
    return { view: await listEquipmentSupport(), error: null };
  } catch (error) {
    if (error instanceof CoreApiError) return { view: null, error };
    throw error;
  }
}

function LevelProgress({ record }: { record: EquipmentSupportView }) {
  const reached = SUPPORT_LEVEL_ORDER.indexOf(record.state);
  return (
    <div className="flex items-center gap-1" aria-label={`검증 단계 ${reached + 1}/6`}>
      {SUPPORT_LEVEL_ORDER.map((level, index) => (
        <span
          key={level}
          title={SUPPORT_LEVEL_LABEL[level]}
          className={`h-1.5 w-6 rounded-full ${
            index <= reached ? "bg-emerald-500" : "bg-neutral-200"
          }`}
        />
      ))}
    </div>
  );
}

/**
 * 장비 지원단계 표 (MASTER_PRD §23.3/§26.7 "장비 지원상태를 고객 UI와 계약에
 * 정직하게 표시").
 *
 * **`productionSupported` 가 true 인 것만 "상용 지원"으로 표시한다.** 그 판정은
 * 서버가 `is_production_supported()` 로 계산해 내려준 값이고, 이 화면은 `state`
 * 문자열을 보고 스스로 판단하지 않는다 — 그러면 단계가 추가되는 날 조용히 틀린다
 * (`docs/00_READ_FIRST.md` 구현 금지 "미검증 장비를 상용지원으로 표시").
 *
 * 승급·강등은 여기서 하지 않는다 — `EQUIPMENT_SUPPORT_APPROVE`(ADMIN 전용) 권한
 * 표면이고, 그 조작 UI 는 증거 첨부 흐름과 함께 별도로 설계해야 한다. 지금 화면은
 * **정직한 표시**라는 §26.7 의 요구를 먼저 충족한다.
 */
export default async function SettingsPage() {
  const { view, error } = await fetchSupport();

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

  if (view.classCount === 0) {
    return (
      <div className="p-4 sm:p-5">
        <EmptyState
          title="등록된 장비 클래스가 없습니다"
          description="장비 지원단계는 관리자가 클래스를 등록한 뒤 검증 단계를 올리면서 쌓입니다. 데이터셋이 있다는 것만으로는 지원으로 표시하지 않습니다."
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 p-4 sm:p-5">
      <section className="rounded-lg border border-neutral-200 p-4">
        <h2 className="text-sm font-semibold">장비 지원 현황</h2>
        <p className="mt-1 text-sm text-neutral-600">
          등록 {view.classCount}종 중 <strong>상용 지원 {view.productionSupportedCount}종</strong>.
          나머지는 검증 중이며 상용 안전지원으로 표시하지 않습니다.
        </p>
      </section>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[44rem] text-left text-sm">
          <thead className="border-b border-neutral-200 text-xs uppercase text-neutral-500">
            <tr>
              <th className="px-3 py-2">장비 클래스</th>
              <th className="px-3 py-2">검증 단계</th>
              <th className="px-3 py-2">진행</th>
              <th className="px-3 py-2">상용 지원</th>
              <th className="px-3 py-2">모델 버전</th>
              <th className="px-3 py-2">근거</th>
            </tr>
          </thead>
          <tbody>
            {view.classes.map((record) => (
              <tr
                key={record.classId}
                className="border-b border-neutral-100"
              >
                <td className="px-3 py-2 font-medium">{record.classId}</td>
                <td className="px-3 py-2">{SUPPORT_LEVEL_LABEL[record.state]}</td>
                <td className="px-3 py-2">
                  <LevelProgress record={record} />
                </td>
                <td className="px-3 py-2">
                  {/* 서버 파생값만 본다 — state 문자열로 다시 판단하지 않는다. */}
                  {record.productionSupported ? (
                    <span className="rounded bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-800">
                      상용 지원
                    </span>
                  ) : (
                    <span className="rounded bg-neutral-100 px-2 py-0.5 text-xs text-neutral-600">
                      검증 중
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-neutral-600">
                  {record.modelVersion ?? "—"}
                </td>
                <td className="px-3 py-2 text-neutral-600">
                  {record.evidenceRefs.length === 0
                    ? "—"
                    : `${record.evidenceRefs.length}건`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
