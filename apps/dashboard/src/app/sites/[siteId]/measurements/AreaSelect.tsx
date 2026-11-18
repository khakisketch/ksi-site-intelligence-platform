"use client";

import type { ReactNode } from "react";

/** 서버의 GET 폼과 범위 검증을 그대로 쓴다. JS가 없으면 조회 버튼으로 제출한다. */
export function AreaSelect({ value, children }: { value: string; children: ReactNode }) {
  return <select
    id="measurement-work-area"
    name="workAreaId"
    className="input"
    defaultValue={value}
    required
    onChange={(event) => { if (event.currentTarget.value) event.currentTarget.form?.requestSubmit(); }}
  >{children}</select>;
}
