"use client";

import { useId, type ReactNode } from "react";

/**
 * 한국어 일관 파일 선택기 — 네이티브 `<input type="file">` 의 브라우저 로케일
 * chrome("Choose File / No file chosen", "선택된 파일 없음")을 화면에 노출하지 않는다.
 *
 * 입력 자체는 접근성을 위해 DOM 에 남긴다(sr-only): 라벨 클릭·키보드 포커스 모두
 * 네이티브 동작을 유지하고, `getByLabelText` 기반 계약 테스트도 그대로 산다.
 */
export function FilePickerField({
  label,
  ariaLabel,
  accept,
  disabled = false,
  onSelect,
  selectedFileName = null,
  selectedHint = null,
  triggerLabel = "파일 선택",
}: {
  label: ReactNode;
  ariaLabel: string;
  accept?: string;
  disabled?: boolean;
  onSelect: (file: File | null) => void;
  selectedFileName?: string | null;
  selectedHint?: string | null;
  triggerLabel?: string;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <span className="font-semibold">{label}</span>
      <div className="flex flex-wrap items-center gap-2">
        <label
          htmlFor={id}
          className={`btn w-fit ${disabled ? "pointer-events-none opacity-60" : "cursor-pointer"}`}
        >
          {triggerLabel}
        </label>
        <span className="text-[12.5px] leading-5 text-ink-2">
          {selectedFileName ?? "선택된 파일 없음"}
          {selectedFileName !== null && selectedHint ? ` · ${selectedHint}` : ""}
        </span>
      </div>
      <input
        id={id}
        className="sr-only"
        aria-label={ariaLabel}
        type="file"
        accept={accept}
        disabled={disabled}
        onClick={(event) => {
          // 같은 파일을 다시 고를 수 있게 값을 비운다(change 가 다시 발화한다).
          event.currentTarget.value = "";
        }}
        onChange={(event) => onSelect(event.target.files?.[0] ?? null)}
      />
    </div>
  );
}
