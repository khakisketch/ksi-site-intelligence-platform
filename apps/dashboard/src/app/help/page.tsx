import Link from "next/link";

const tasks = [
  { title: "현장 자료 살펴보기", detail: "현장 선택 → 작업구역 → 관측 시점", href: "/sites", action: "현장 목록" },
  { title: "관측 자료 등록하기", detail: "현장·작업구역 선택 → 파일 제출 → 검사", href: "/field/new", action: "관측 자료 등록" },
  { title: "배정·공유된 항목 확인하기", detail: "받은 업무 → 작업 또는 외부 비교 결과", href: "/field/inbox", action: "받은 업무" },
];

function DisclosureMark() {
  return <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" className="ml-auto size-4 shrink-0 transition-transform group-open:rotate-180"><path d="m5 7 5 5 5-5" /></svg>;
}

export default function HelpPage() {
  return <div className="console-page">
    <header className="console-page-heading"><div><h2 className="console-page-title">도움말</h2><p className="console-page-description">하려는 작업에서 시작하세요.</p></div><Link href="/more" className="btn">내 계정</Link></header>
    <div className="grid max-w-5xl gap-8 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] xl:gap-12">
      <section aria-labelledby="help-tasks"><h3 id="help-tasks" className="mb-3 text-[16px] font-semibold">작업 시작</h3><ul className="divide-y divide-line border-y border-line">{tasks.map((task) => <li key={task.href}><Link href={task.href} className="tap-target flex items-center justify-between gap-4 py-5 hover:underline"><span><span className="block text-[14px] font-semibold">{task.title}</span><span className="mt-1 block text-[12px] leading-5 text-ink-2">{task.detail}</span></span><svg aria-hidden="true" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" className="size-4 shrink-0"><path d="m7 4 6 6-6 6" /></svg><span className="sr-only">{task.action}</span></Link></li>)}</ul></section>
      <section aria-labelledby="help-questions"><h3 id="help-questions" className="mb-3 text-[16px] font-semibold">자주 확인하는 내용</h3><div className="divide-y divide-line border-y border-line">
        <details className="group py-3"><summary className="tap-target flex cursor-pointer items-center gap-3 text-[13px] font-medium">자료가 등록됐는데 미리보기가 없어요<DisclosureMark /></summary><p className="pb-2 text-[13px] leading-6 text-ink-2">자료 등록과 미리보기 준비는 별개입니다. 현장의 자료에서 검사·준비 상태를 확인하세요. 보관 기간이 끝났다면 구역 자료 준비에서 현재 가능한 작업을 확인할 수 있습니다. 미리보기 부재가 등록 기록의 삭제를 뜻하지는 않습니다.</p></details>
        <details className="group py-3"><summary className="tap-target flex cursor-pointer items-center gap-3 text-[13px] font-medium">화면을 볼 수 있으면 물량 분석도 가능한가요?<DisclosureMark /></summary><p className="pb-2 text-[13px] leading-6 text-ink-2">아닙니다. 열람·분석 적합성·정확도 평가·사람 검토는 서로 다릅니다. 결과 화면에서 입력별 조건과 부족한 근거를 확인하세요. 비교 화면의 A·B 선택은 계산 입력을 변경하지 않습니다.</p></details>
        <details className="group py-3"><summary className="tap-target flex cursor-pointer items-center gap-3 text-[13px] font-medium">휴대폰에서 등록을 계속할 수 있나요?<DisclosureMark /></summary><p className="pb-2 text-[13px] leading-6 text-ink-2">휴대폰에서는 현장·자료·결과를 확인할 수 있습니다. 현장 등록과 작업 생성 등 노트북 전용 행동은 같은 계정으로 노트북에서 열어 진행하세요.</p></details>
      </div><Link href="/coming-soon/fleet" className="tap-target mt-4 inline-flex items-center text-[12px] text-ink-2 underline">Dock·Edge 지원 범위</Link><p className="text-[12px] text-ink-muted">장비 운용과 고객 측 재구성은 제품 범위 밖입니다.</p></section>
    </div>
  </div>;
}
