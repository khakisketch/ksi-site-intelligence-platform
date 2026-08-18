import Link from "next/link";

/**
 * 첫 실행 화면(Console v2 §2) — 등록된 현장이 0곳일 때만 나온다.
 *
 * 빈 목록에 "현장이 없습니다"만 두면, 처음 켠 사람은 **다음에 뭘 해야 결과가
 * 나오는지**를 모른 채 등록 버튼을 누른다. 이 제품의 첫 조사는 그 자체로 끝이
 * 아니라 기준 모델을 만드는 단계이고, 변화·물량·재관측은 **두 번째 조사부터**
 * 나온다 — 그 사실을 처음에 말하지 않으면 첫 조사 결과를 보고 "왜 아무것도 없나"가 된다.
 *
 * 시안 문구 중 "조사 주기"와 "5분이면 끝납니다"는 뺐다. 이 시스템에는 조사 주기라는
 * 값이 없고(현장이 가진 것은 모델 노후 판정 기준일 뿐이다), 소요 시간은 아무도 재본
 * 적 없는 숫자다.
 */
const STEPS = [
  {
    title: "현장 등록",
    body: "현장 이름과 외곽 경계를 등록합니다. 좌표계는 등록할 때 정한 값을 이후 화면이 그대로 씁니다.",
  },
  {
    title: "초기 매핑 비행",
    body: "발급된 비행 파일(KMZ)을 DJI Pilot 2로 받아 촬영하면 그 사진으로 기준 모델이 만들어집니다.",
  },
  {
    title: "두 번째 조사부터 분석",
    body: "변화 영역·물량·재관측 제안은 비교할 이전 시점이 있어야 계산됩니다 — 두 번째 조사부터 나옵니다.",
  },
];

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
          첫 조사가 끝나면 기준 모델이 만들어지고, 두 번째 조사부터 변화·물량·재관측이 계산됩니다.
        </p>
      </div>

      <ol className="grid w-full gap-3 text-left sm:grid-cols-3">
        {STEPS.map((step, index) => (
          <li key={step.title} className="rounded-lg border border-line bg-surface p-4">
            <span
              className={`num grid size-6 place-items-center rounded-md text-[12px] font-bold ${
                index === 0 ? "bg-accent text-accent-on" : "bg-sunk text-ink-2"
              }`}
            >
              {index + 1}
            </span>
            <p className="mt-2 text-[13.5px] font-bold break-keep">{step.title}</p>
            <p className="mt-1 text-[12px] leading-relaxed break-keep text-ink-2">{step.body}</p>
          </li>
        ))}
      </ol>

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
