"use client";

import { useId, useState, type DragEvent } from "react";

/**
 * 정사영상과 DSM을 한 번에 끌어 놓거나 고르는 입력. 칸 배정은 부모가 헤더로 정한다.
 * 키보드·스크린리더는 숨은 파일 입력(라벨)으로 같은 동작을 한다.
 */
export function ExternalFileDropZone({ disabled, onFiles }: { disabled: boolean; onFiles: (files: File[]) => void }) {
  const id = useId();
  const [over, setOver] = useState(false);
  const stop = (event: DragEvent) => {
    event.preventDefault();
    event.stopPropagation();
  };
  return <div
    data-testid="external-file-drop-zone"
    className={`flex flex-col items-start gap-2 rounded-lg border border-dashed px-4 py-3 ${over && !disabled ? "border-accent bg-sunk" : "border-line"} ${disabled ? "opacity-60" : ""}`}
    onDragEnter={(event) => { stop(event); if (!disabled) setOver(true); }}
    onDragOver={(event) => { stop(event); if (!disabled) setOver(true); }}
    onDragLeave={(event) => { stop(event); setOver(false); }}
    onDrop={(event) => {
      stop(event);
      setOver(false);
      if (disabled) return;
      const files = Array.from(event.dataTransfer?.files ?? []);
      if (files.length > 0) onFiles(files);
    }}
  >
    <p className="font-semibold">파일을 여기에 끌어 놓으세요</p>
    <p className="text-[12px] leading-5 text-ink-2">정사영상과 DSM을 함께 놓아도 파일 내용으로 알아서 칸을 나눕니다. 아래 칸에서 하나씩 고를 수도 있습니다.</p>
    <label htmlFor={id} className={`btn w-fit ${disabled ? "pointer-events-none" : "cursor-pointer"}`}>여러 파일 한 번에 선택</label>
    <input
      id={id}
      className="sr-only"
      type="file"
      multiple
      accept=".tif,.tiff"
      aria-label="정사영상·DSM 파일 한 번에 선택"
      disabled={disabled}
      onClick={(event) => { event.currentTarget.value = ""; }}
      onChange={(event) => { const files = Array.from(event.target.files ?? []); if (files.length > 0) onFiles(files); }}
    />
  </div>;
}
