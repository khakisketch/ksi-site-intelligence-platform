import Link from "next/link";

export function SiteOnboarding({ canRegisterSite }: { canRegisterSite: boolean }) {
  return (
    <section className="mx-auto flex w-full max-w-3xl flex-col items-center gap-5 py-10 text-center">
      <div className="flex flex-col items-center gap-1.5">
        <p className="text-[11px] font-bold tracking-wider break-keep text-ink-muted">
          첫 실행 · 등록된 현장 0곳
        </p>
        <h2 className="text-[22px] font-bold tracking-tight break-keep">
          현장을 등록하면 여기서 시작합니다
        </h2>
        <p className="max-w-xl text-[13px] break-keep text-ink-2">
          현장 이름과 외곽 경계를 등록한 뒤, 현장 화면에서 작업구역과 등록된 플랫폼 기록을 확인할 수 있습니다.
        </p>
      </div>

      {canRegisterSite ? (
        <Link href="/sites/new" className="btn btn-primary tap-target">
          첫 현장 등록하기
        </Link>
      ) : (
        <p className="text-[12.5px] break-keep text-ink-muted">
          현장 등록은 현장 등록 권한을 가진 계정만 할 수 있습니다.
        </p>
      )}
    </section>
  );
}
