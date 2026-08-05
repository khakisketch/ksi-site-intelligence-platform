"use client";

// 목록의 17개 필터 칩 중 대기열 4칸(트리아지)만 상단 집계 버튼으로 남기고 나머지
// enum(상태7 · 심각도4 · 트리아지 나머지 2)은 이 select 로 내린다 — events/page.tsx 전용.
import { useRouter } from "next/navigation";

export interface FilterSelectParams {
  siteId?: string;
  missionId?: string;
  edgeDeviceId?: string;
  status?: string;
  severity?: string;
  triage?: string;
}

export function FilterSelect({
  label,
  paramKey,
  value,
  options,
  currentParams,
}: {
  label: string;
  paramKey: keyof FilterSelectParams;
  value: string;
  options: { value: string; label: string }[];
  currentParams: FilterSelectParams;
}) {
  const router = useRouter();

  function handleChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const next = new URLSearchParams();
    for (const [k, v] of Object.entries(currentParams)) {
      if (typeof v === "string" && v && k !== paramKey) next.set(k, v);
    }
    if (e.target.value) next.set(paramKey, e.target.value);
    const qs = next.toString();
    router.push(qs ? `/events?${qs}` : "/events");
  }

  return (
    <label className="flex items-center gap-1.5 text-[12.5px] break-keep text-ink-2">
      <span>{label}</span>
      <select className="input w-auto" value={value} onChange={handleChange}>
        <option value="">전체</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}
