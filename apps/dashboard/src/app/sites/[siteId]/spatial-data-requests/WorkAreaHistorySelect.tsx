"use client";

import type { ReactNode } from "react";

// 서버의 GET form·범위 검증을 그대로 사용한다. JS가 없으면 기존 제출 버튼으로 조회한다.
export function WorkAreaHistorySelect({ value, children }: { value: string; children: ReactNode }) {
  return <select
    id="spatial-request-work-area"
    name="workAreaId"
    className="input"
    defaultValue={value}
    required
    aria-describedby="spatial-request-work-area-help"
    onChange={(event) => { if (event.currentTarget.value) event.currentTarget.form?.requestSubmit(); }}
  >{children}</select>;
}
