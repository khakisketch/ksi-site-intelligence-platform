import type { DraftStorageStatus } from "@/hooks/useDraftState";
import { SiteRegistrationRecoveryGuidance } from "./SiteRegistrationRecoveryGuidance";

type StorageGateStatus = Extract<DraftStorageStatus, "loading" | "unreadable" | "unavailable">;

/** 저장된 초안의 존재나 형식을 확인하지 못할 때 기존 기록을 추측·덮어쓰지 않는다. */
export function SiteRegistrationStorageGate({ status }: { status: StorageGateStatus }) {
  return (
    <div className="console-page !max-w-[960px]">
      <header className="console-page-heading">
        <h2 className="console-page-title">현장 등록</h2>
      </header>
      {status === "loading" ? (
        <p role="status" className="rounded-lg border border-line bg-sunk p-4 text-sm text-ink-2">
          저장된 입력을 확인하고 있습니다.
        </p>
      ) : (
        <section role="alert" className="flex flex-col items-start gap-3 rounded-lg border border-line-strong bg-sunk p-4 text-sm text-ink-1">
          <h3 className="font-semibold break-keep">
            {status === "unreadable" ? "저장된 현장 초안을 읽을 수 없습니다" : "현장 초안 저장소를 확인할 수 없습니다"}
          </h3>
          <p className="break-keep text-ink-2">
            {status === "unreadable"
              ? "저장된 내용의 형식을 확인하지 못했습니다. 원본을 덮어쓰지 않았으며, 이 화면에서는 등록하지 않습니다. 현장 목록에서 이전 요청을 먼저 확인하세요."
              : "브라우저 저장소를 읽지 못해 이전 초안이 있는지 확인할 수 없습니다. 기존 기록을 덮어쓰지 않도록 이 화면에서는 등록하지 않습니다. 저장소 설정을 확인한 뒤 다시 열어 주세요."}
          </p>
          <SiteRegistrationRecoveryGuidance />
        </section>
      )}
    </div>
  );
}
