import { SiteSelectionForm } from "@/app/sites/[siteId]/SiteSelectionForm";

/**
 * 칸별 관측 선택 — 각 이미지 바로 위에서 그 칸의 관측만 바꾼다.
 *
 * - 후보는 호출자가 이미 읽은 같은 범위 목록에서 같은 종류만 둔다(같은
 *   제출 묶음의 층 전환은 아래 뷰어가 맡는다). 날짜 정밀도는 Core 사실
 *   그대로, 버전은 v표기로만 가른다 — 최신·기준 같은 시간 서열을 짓지 않는다.
 * - 이동은 기존 URL 키(visualA/B·필터·info·cursor·옛 assetRef) 그대로의 GET이다.
 *   모양이 어긋난 선택은 기존 fail-closed가 받는다. 여기서 조용히 다른
 *   자료로 바꾸거나 지원하지 않는 층으로 전환하지 않는다.
 * - 후보가 2건 미만이면 상자 대신 현재 한 줄만 둔다 — 날짜는 항상 칸 위에 둔다.
 */
export function PaneObservationSelect({
  action,
  side,
  sideParam,
  currentRef,
  currentLabel,
  options,
  hidden,
}: {
  /** 목록 주소(구역 포함). */
  action: string;
  /** 칸 역할 — 라벨용. */
  side: "A" | "B";
  /** 이 칸이 바꾸는 쿼리 키. */
  sideParam: "visualAAssetRef" | "visualBAssetRef";
  /** 현재 칸이 보는 자산 참조. */
  currentRef: string;
  /** 현재 칸의 사람용 한 줄 표기(날짜·버전). 후보가 하나뿐일 때도 둔다. */
  currentLabel: string;
  /** 같은 종류 후보 — 정확한 참조와 사람용 라벨. */
  options: Array<{ assetRef: string; label: string; title: string }>;
  /** 함께 싣는 기존 범위(작업구역·반대쪽 참조·필터·info·cursor·옛 참조). */
  hidden: Array<readonly [string, string]>;
}) {
  if (options.length < 2) {
    return <p className="min-w-0 truncate text-[12.5px] font-semibold" title={currentLabel}>{currentLabel}</p>;
  }
  return (
    <SiteSelectionForm action={action} className="min-w-0">
      {hidden.map(([name, value]) => (
        <input key={name} type="hidden" name={name} value={value} />
      ))}
      <label className="sr-only" htmlFor={`pane-observation-${sideParam}`}>
        {side} 관측 선택
      </label>
      <select
        id={`pane-observation-${sideParam}`}
        name={sideParam}
        defaultValue={currentRef}
        required
        className="input min-w-0 w-full max-w-56 text-[12.5px]"
      >
        {options.map((option) => (
          <option key={option.assetRef} value={option.assetRef} title={option.title}>
            {option.label}
          </option>
        ))}
      </select>
    </SiteSelectionForm>
  );
}
