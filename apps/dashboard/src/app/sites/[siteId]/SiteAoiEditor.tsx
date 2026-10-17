"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { AoiPolygonMap } from "@/components/map/AoiPolygonMap";
import { useMutation } from "@/hooks/useMutation";
import type { AoiVertex, SiteFrame } from "@/lib/core-api/types";

/**
 * 현장 상세에서 AOI 를 직접 설정하는 편집기 — `UNMAPPED` 상태에서만 렌더된다
 * (호출부가 서버 게이트와 같은 조건으로 가드, `SiteStore.set_aoi` 대칭).
 *
 * `SiteRegistrationOnlyWizard`(SITES_WRITE 만 있고 MISSIONS_ISSUE 가 없는 역할의
 * 등록 경로)는 AOI 단계가 없어, 그 경로로 등록된 현장은 이 화면이 유일한 진입점이다
 * (독립 반증 D3).
 */
export function SiteAoiEditor({ siteId, siteFrame }: { siteId: string; siteFrame: SiteFrame }) {
  const router = useRouter();
  const [vertices, setVertices] = useState<AoiVertex[]>([]);
  const [pending, setPending] = useState(false);
  const { mutate, errorMessage } = useMutation();

  const canSubmit = vertices.length >= 3 && !pending;

  async function submit() {
    if (!canSubmit) return;
    setPending(true);
    await mutate(
      `/api/sites/${encodeURIComponent(siteId)}/aoi`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ aoi: { vertices }, siteFrame }),
      },
      () => {
        router.refresh();
      },
    );
    setPending(false);
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-[12.5px] break-keep text-ink-muted">
        현장 전체의 경계를 설정합니다. 자료 등록·비교에 사용하는 작업구역과는 별개이며,
        전체 경계가 없어도 작업구역에 연결된 자료를 등록할 수 있습니다.
      </p>
      <AoiPolygonMap value={vertices} onChange={setVertices} />
      <button
        type="button"
        className="btn btn-primary self-start"
        disabled={!canSubmit}
        onClick={submit}
      >
        {pending ? "저장 중…" : "현장 범위 저장"}
      </button>
      {errorMessage && (
        <p role="alert" className="break-keep text-[12.5px] text-crit-ink">
          {errorMessage}
        </p>
      )}
    </div>
  );
}
