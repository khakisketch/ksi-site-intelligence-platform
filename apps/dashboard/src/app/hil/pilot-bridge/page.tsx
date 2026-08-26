import { notFound } from "next/navigation";

import { PilotBridgeProbe } from "@/app/field/PilotBridgeProbe";

export const metadata = { title: "Pilot Bridge HIL · KSI" };

export default function PilotBridgeHilPage() {
  if (
    process.env.NODE_ENV === "production" ||
    process.env.KSI_DASHBOARD_HIL_TOOLS_ENABLED !== "1"
  ) {
    notFound();
  }

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-5">
      <header className="flex flex-col gap-1">
        <p className="text-[11px] font-semibold tracking-[0.08em] text-ink-muted uppercase">
          HIL diagnostics only
        </p>
        <h2 className="text-[19px] font-bold tracking-tight">Pilot Bridge 진단</h2>
        <p className="max-w-3xl text-[13px] leading-6 break-keep text-ink-2">
          이 화면은 장비 검증용이며 Operations Console 제품 기능이 아닙니다. production에서는
          항상 404를 반환합니다.
        </p>
      </header>
      <PilotBridgeProbe />
    </div>
  );
}
