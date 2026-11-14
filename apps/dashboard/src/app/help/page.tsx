import Link from "next/link";

import { Disclosure } from "@/components/ui/Disclosure";
import { PageHeader } from "@/components/ui/PageHeader";

const tasks = [
  { title: "현장 공간과 분석 보기", detail: "공간에서 관측 자료를 고르고 분석에서 변화 기록을 확인합니다.", href: "/sites" },
  { title: "관측 자료 등록하기", detail: "현장과 작업구역을 선택하고 파일을 제출합니다.", href: "/field/new" },
  { title: "배정·공유된 항목 확인하기", detail: "나에게 배정된 작업과 공유된 외부 비교 결과를 엽니다.", href: "/field/inbox" },
  { title: "조직의 작업 기록 보기", detail: "등록·검사 진행 상태를 현장별로 거릅니다.", href: "/field" },
];

const topics = [
  {
    title: "공간·분석·작업 상세",
    detail: "공간에서는 자료를 등록하고, 자료별 검사 상태와 두 관측 시점을 살펴봅니다. 분석에서는 변화 분석을 요청하고 결과·이력과 외부 비교를 검토합니다. 작업은 조직의 작업 기록을 현장별로 걸러 볼 수 있으며, 받은 작업은 나에게 배정되거나 공유된 항목입니다.",
  },
  {
    title: "자료 미리보기 상세",
    detail: "공간의 자료 패널에서 검사·준비 상태를 확인할 수 있습니다. 보관 기간이 끝났다면 구역 자료 준비에서 현재 가능한 작업을 확인하세요.",
  },
  {
    title: "분석 조건 상세",
    detail: "분석 결과에서 입력별 분석 적합성과 추가 확인이 필요한 근거를 확인하세요. 공간에서 선택한 비교 시점은 분석 요청의 입력을 바꾸지 않습니다.",
  },
  {
    title: "휴대폰 이용 상세",
    detail: "휴대폰에서 공간과 분석을 볼 수 있습니다. 현장 등록과 작업 생성은 같은 계정으로 노트북에서 열어 진행하세요.",
  },
];

export default function HelpPage() {
  return (
    <div className="console-page">
      <PageHeader title="도움말" headingLevel={2} actions={<Link href="/more" className="btn">내 계정</Link>} />
      <div className="grid max-w-5xl gap-8 xl:grid-cols-2 xl:gap-12">
        <section aria-labelledby="help-tasks">
          <h3 id="help-tasks" className="mb-3 text-title font-semibold">작업 시작</h3>
          <ul className="divide-y divide-line border-y border-line">
            {tasks.map((task) => (
              <li key={task.href}>
                <Link href={task.href} className="tap-target flex items-center justify-between gap-4 py-4 hover:bg-sunk">
                  <span>
                    <span className="block text-lead font-semibold">{task.title}</span>
                    <span className="mt-1 block text-caption text-ink-2">{task.detail}</span>
                  </span>
                  <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" className="size-4 shrink-0"><path d="m7 4 6 6-6 6" /></svg>
                </Link>
              </li>
            ))}
          </ul>
        </section>
        <section aria-labelledby="help-questions">
          <h3 id="help-questions" className="mb-3 text-title font-semibold">자주 확인하는 내용</h3>
          <div className="divide-y divide-line border-y border-line">
            {topics.map((topic) => (
              <Disclosure key={topic.title} label={topic.title} className="py-2">
                <p className="pb-2 text-body text-ink-2">{topic.detail}</p>
              </Disclosure>
            ))}
          </div>
          <p className="mt-4 text-caption text-ink-muted">장비 운용과 고객 측 재구성은 제품 범위 밖입니다. <Link href="/coming-soon/fleet" className="font-semibold text-ink-2 underline">Dock·Edge 지원 범위</Link>를 확인하세요.</p>
        </section>
      </div>
    </div>
  );
}
