import { useEffect, useMemo, useRef, useState, type ComponentType, type ReactNode } from "react";
import {
  ActivityLogIcon,
  ArrowLeftIcon,
  BellIcon,
  ChatBubbleIcon,
  CheckCircledIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  CubeIcon,
  DotsHorizontalIcon,
  DrawingPinIcon,
  ExclamationTriangleIcon,
  HomeIcon,
  LayersIcon,
  PaperPlaneIcon,
  ReaderIcon,
  TargetIcon,
  UpdateIcon,
} from "@radix-ui/react-icons";
import { BottomSheet, Carousel, KeyboardInput, MobileScroll } from "./mobile";

type View = "home" | "sites" | "cases" | "site" | "case-detail" | "ai" | "more";
type NavView = "home" | "sites" | "cases" | "ai" | "more";
type Tone = "attention" | "context" | "ready" | "quiet";
type Sheet = "none" | "sites" | "notifications" | "decision";
type Decision = "FIELD_CHECK" | "REVIEWED";

type Site = {
  id: string;
  name: string;
  location: string;
  tone: Tone;
  status: string;
  summary: string;
  observedAt: string;
};

type Evidence = { label: string; detail: string };

type InsightCase = {
  id: string;
  siteId: string;
  category: string;
  tone: Tone;
  status: string;
  title: string;
  claim: string;
  why: string;
  uncertainty: string;
  signal: string;
  observedAt: string;
  evidence: Evidence[];
};

const sites: Site[] = [
  {
    id: "seocho",
    name: "서초 복합물류센터",
    location: "서울 서초구 · 토공 남측 구역",
    tone: "attention",
    status: "근거 보충 필요",
    summary: "남측 토공 구역의 촬영 범위가 부족해 진척 판단이 제한됩니다.",
    observedAt: "8월 22일 10:42",
  },
  {
    id: "gimpo",
    name: "김포 제조공장",
    location: "경기 김포시 · 골조 동측 구역",
    tone: "context",
    status: "현장 맥락 필요",
    summary: "골조 변화는 확인됐지만 계획 일정과 아직 연결되지 않았습니다.",
    observedAt: "8월 21일 16:18",
  },
  {
    id: "incheon",
    name: "인천 자재야적장",
    location: "인천 서구 · 야적 A구역",
    tone: "ready",
    status: "결과 준비",
    summary: "7월 관측 대비 야적 체적의 상대 변화가 계산됐습니다.",
    observedAt: "8월 20일 09:36",
  },
  {
    id: "pangyo",
    name: "판교 데이터센터",
    location: "경기 성남시 · 외곽 전체",
    tone: "quiet",
    status: "새 안건 없음",
    summary: "최근 관측에서 별도로 검토할 변화가 생성되지 않았습니다.",
    observedAt: "8월 19일 14:05",
  },
];

const cases: InsightCase[] = [
  {
    id: "case-capture",
    siteId: "seocho",
    category: "촬영 근거",
    tone: "attention",
    status: "결정 필요",
    title: "남측 토공 구역은 추가 근거가 필요합니다",
    claim: "8월 22일 관측에서 남측 작업구역의 유효 촬영 범위가 61%로 확인됐습니다.",
    why: "현재 데이터만으로도 지형 변화는 보이지만 구역 전체의 공정 상태를 대표한다고 말하기 어렵습니다.",
    uncertainty: "남서측 경계와 임시 적치물 뒤편이 촬영되지 않았습니다. 절대 물량이나 일정 영향은 판단하지 않았습니다.",
    signal: "유효 촬영 범위 61%",
    observedAt: "8월 22일 10:42",
    evidence: [
      { label: "촬영 범위 보고", detail: "남측 작업구역 61% · 미관측 셀 14개" },
      { label: "시점 비교 결과", detail: "8월 1일 ↔ 8월 22일 · 지형 변화 후보 3개" },
      { label: "원본 계보", detail: "검증된 원본 184장 · 누락 구간 2곳" },
    ],
  },
  {
    id: "case-progress",
    siteId: "gimpo",
    category: "공정 변화",
    tone: "context",
    status: "현장 확인 필요",
    title: "동측 골조 변화의 공정 의미를 확인해야 합니다",
    claim: "이전 관측과 비교해 동측 골조 구역의 형상 변화가 확인됐습니다.",
    why: "공정 진행으로 보이는 변화지만 현재 KSI에는 이 구역의 기준 일정과 공종 연결 정보가 없습니다.",
    uncertainty: "실제 완료 공정과 일정 영향은 현장 담당자의 맥락 확인 전까지 확정할 수 없습니다.",
    signal: "변화 구역 2곳",
    observedAt: "8월 21일 16:18",
    evidence: [
      { label: "3D 시점 비교", detail: "8월 7일 ↔ 8월 21일 · 동측 형상 변화" },
      { label: "공간 위치", detail: "골조 동측 작업구역 · 비교 좌표계 일치" },
      { label: "부족한 업무 맥락", detail: "기준 일정·WBS 연결 없음" },
    ],
  },
  {
    id: "case-volume",
    siteId: "incheon",
    category: "상대 물량",
    tone: "ready",
    status: "결과 준비",
    title: "야적 A구역의 상대 체적이 증가했습니다",
    claim: "7월 25일 관측 대비 야적 A구역의 계산 체적이 14% 증가했습니다.",
    why: "현장 자재 흐름을 설명하는 참고 결과로 사용할 수 있습니다.",
    uncertainty: "동일 기준면을 사용한 시점 간 상대값입니다. 계약 정산용 절대 물량으로 사용할 수 없습니다.",
    signal: "이전 시점 대비 +14%",
    observedAt: "8월 20일 09:36",
    evidence: [
      { label: "상대 물량 보고", detail: "7월 25일 ↔ 8월 20일 · 기준면 동일" },
      { label: "표면 모델", detail: "두 시점 DSM 검증 완료" },
      { label: "사용 제한", detail: "상대 변화 참고용 · 정산용 아님" },
    ],
  },
];

const toneCopy: Record<Tone, string> = {
  attention: "근거 부족",
  context: "맥락 필요",
  ready: "결과 준비",
  quiet: "안정",
};

function getSite(siteId: string) {
  return sites.find((site) => site.id === siteId) ?? sites[0];
}

function getCase(caseId: string) {
  return cases.find((item) => item.id === caseId) ?? cases[0];
}

function StatusBadge({ tone, children }: { tone: Tone; children?: ReactNode }) {
  return <span className={`status-badge status-badge--${tone}`}>{children ?? toneCopy[tone]}</span>;
}

function AppTopbar({ onHome, onNotifications, hasUnread }: { onHome: () => void; onNotifications: () => void; hasUnread: boolean }) {
  return (
    <header className="app-topbar">
      <button className="brand-button" type="button" aria-label="홈으로 이동" onClick={onHome}>KSI</button>
      <button className="icon-button notification-button" type="button" aria-label="알림 열기" onClick={onNotifications}>
        <BellIcon aria-hidden="true" />
        {hasUnread ? <span className="notification-indicator" /> : null}
      </button>
    </header>
  );
}

function PageIntro({ eyebrow, title, copy }: { eyebrow: string; title: string; copy: string }) {
  return <header className="page-intro"><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p>{copy}</p></header>;
}

function SectionHeading({ title, trailing }: { title: string; trailing?: ReactNode }) {
  return <div className="section-heading"><h2>{title}</h2>{trailing}</div>;
}

function InsightRow({ item, decision, onOpen }: { item: InsightCase; decision?: Decision; onOpen: () => void }) {
  const site = getSite(item.siteId);
  const status = decision === "FIELD_CHECK" ? "담당자 확인 요청됨" : decision === "REVIEWED" ? "검토 완료" : item.status;
  return (
    <button className="insight-row" type="button" onClick={onOpen} aria-label={`${site.name}, ${item.title}`}>
      <span className={`insight-row__marker insight-row__marker--${decision ? "quiet" : item.tone}`} aria-hidden="true" />
      <span className="insight-row__body">
        <span className="insight-row__topline"><strong>{site.name}</strong><small>{status}</small></span>
        <span className="insight-row__title">{item.title}</span>
        <span className="insight-row__meta">{item.category} · {item.signal}</span>
      </span>
      <ChevronRightIcon className="insight-row__chevron" aria-hidden="true" />
    </button>
  );
}

function PortfolioHome({ decisions, openCase, openCases, openSites, openAi }: { decisions: Record<string, Decision>; openCase: (id: string) => void; openCases: () => void; openSites: () => void; openAi: () => void }) {
  const pending = cases.filter((item) => item.tone !== "ready" && !decisions[item.id]);
  return (
    <main className="screen-content home-screen" data-testid="portfolio-home">
      <section className="portfolio-cover" aria-labelledby="portfolio-title">
        <div className="portfolio-cover__heading">
          <div><p className="eyebrow">8월 23일 · 전사 현황</p><h1 id="portfolio-title">4개 현장</h1></div>
          <button type="button" onClick={openSites}>전체 보기<ChevronRightIcon /></button>
        </div>
        <p className="portfolio-cover__summary">이번 관측에서는 <strong>{pending.length}개 안건</strong>을 살펴볼 이유가 있습니다. 한 곳은 촬영 근거가 부족하고, 한 곳은 현장 일정 맥락이 필요합니다.</p>
        <dl className="portfolio-facts">
          <div><dt>새 안건</dt><dd>{pending.length}</dd></div>
          <div><dt>근거 부족</dt><dd>{pending.filter((item) => item.tone === "attention").length}</dd></div>
          <div><dt>최근 관측</dt><dd>4/4</dd></div>
        </dl>
      </section>

      <section className="home-section" aria-labelledby="priority-title">
        <SectionHeading title="지금 볼 안건" trailing={<button className="text-button" type="button" onClick={openCases}>전체 {cases.length}건</button>} />
        <div className="insight-list insight-list--strong">
          {pending.length ? pending.slice(0, 2).map((item) => <InsightRow key={item.id} item={item} decision={decisions[item.id]} onOpen={() => openCase(item.id)} />) : <div className="calm-empty"><CheckCircledIcon /><span><strong>새로운 판단 대기 안건이 없습니다</strong><small>완료된 결과는 안건에서 다시 볼 수 있습니다.</small></span></div>}
        </div>
      </section>

      <section className="home-section home-section--compact" aria-labelledby="coverage-title">
        <SectionHeading title="관측 상태" />
        <button className="coverage-row" type="button" onClick={openSites}>
          <UpdateIcon aria-hidden="true" /><span><strong>모든 현장에 최근 관측이 있습니다</strong><small>가장 오래된 관측 · 판교 데이터센터 · 4일 전</small></span><ChevronRightIcon aria-hidden="true" />
        </button>
      </section>

      <button className="ask-entry" type="button" onClick={openAi}><ChatBubbleIcon aria-hidden="true" /><span><strong>전사 현황에 질문</strong><small>검증된 근거가 있는 내용만 답합니다</small></span><ChevronRightIcon aria-hidden="true" /></button>
    </main>
  );
}

function SiteList({ openSite }: { openSite: (id: string) => void }) {
  return (
    <main className="screen-content" data-testid="site-list">
      <PageIntro eyebrow="Portfolio" title="현장" copy="현장을 선택하면 관측, 안건, 공간 결과와 보고서를 한곳에서 볼 수 있습니다." />
      <div className="site-list">
        {sites.map((site) => <button className="site-row" type="button" key={site.id} onClick={() => openSite(site.id)}><span className={`site-row__marker site-row__marker--${site.tone}`} aria-hidden="true" /><span className="site-row__body"><span><strong>{site.name}</strong><StatusBadge tone={site.tone}>{site.status}</StatusBadge></span><small>{site.summary}</small><em>최근 관측 · {site.observedAt}</em></span><ChevronRightIcon aria-hidden="true" /></button>)}
      </div>
    </main>
  );
}

function CaseList({ decisions, openCase }: { decisions: Record<string, Decision>; openCase: (id: string) => void }) {
  const [filter, setFilter] = useState<"all" | "pending" | "ready">("all");
  const visible = cases.filter((item) => filter === "all" || (filter === "pending" ? !decisions[item.id] && item.tone !== "ready" : item.tone === "ready" || Boolean(decisions[item.id])));
  return (
    <main className="screen-content" data-testid="case-list">
      <PageIntro eyebrow="Evidence to action" title="현장 안건" copy="AI가 변화와 근거를 묶어 사람이 판단할 수 있는 단위로 정리합니다." />
      <div className="filter-tabs" role="group" aria-label="안건 필터">
        {([['all', '전체'], ['pending', '결정 필요'], ['ready', '정리됨']] as const).map(([id, label]) => <button type="button" key={id} className={filter === id ? "is-active" : ""} aria-pressed={filter === id} onClick={() => setFilter(id)}>{label}</button>)}
      </div>
      <div className="insight-list">{visible.map((item) => <InsightRow key={item.id} item={item} decision={decisions[item.id]} onOpen={() => openCase(item.id)} />)}</div>
      <p className="truth-note"><ExclamationTriangleIcon />AI 설명은 검증된 분석 결과를 정리합니다. 계획 정보가 없으면 공정 영향도는 확정하지 않습니다.</p>
    </main>
  );
}

function SiteHome({ site, decisions, onBack, onPickSite, openCase, openAi, onAction }: { site: Site; decisions: Record<string, Decision>; onBack: () => void; onPickSite: () => void; openCase: (id: string) => void; openAi: () => void; onAction: (message: string) => void }) {
  const siteCases = cases.filter((item) => item.siteId === site.id);
  return (
    <main className="screen-content" data-testid="site-home">
      <div className="subpage-toolbar"><button className="icon-button" type="button" aria-label="현장 목록으로" onClick={onBack}><ArrowLeftIcon /></button><button className="site-picker-button" type="button" onClick={onPickSite}>{site.name}<ChevronDownIcon /></button><span /></div>
      <header className="site-identity"><p>{site.location}</p><h1>{site.name}</h1><div><StatusBadge tone={site.tone}>{site.status}</StatusBadge><span>최근 관측 {site.observedAt}</span></div></header>

      <section className="site-summary" aria-labelledby="site-summary-title">
        <span className="ai-label"><ActivityLogIcon />KSI AI 요약</span>
        <h2 id="site-summary-title">{site.summary}</h2>
        <p>{siteCases[0]?.why ?? "최근 관측 결과에서 별도의 검토 안건이 생성되지 않았습니다."}</p>
        {siteCases[0] ? <button type="button" onClick={() => openCase(siteCases[0].id)}>근거와 다음 단계 보기<ChevronRightIcon /></button> : null}
      </section>

      <section className="site-section"><SectionHeading title="이 현장의 안건" />{siteCases.length ? <div className="insight-list">{siteCases.map((item) => <InsightRow key={item.id} item={item} decision={decisions[item.id]} onOpen={() => openCase(item.id)} />)}</div> : <div className="calm-empty"><CheckCircledIcon /><span><strong>새 안건이 없습니다</strong><small>최근 관측 결과가 정리되어 있습니다.</small></span></div>}</section>

      <section className="site-section">
        <SectionHeading title="현장 자료" />
        <div className="site-tools">
          <button type="button" onClick={() => onAction("2D·3D 공간뷰는 다음 프로토타입 화면에서 이어집니다")}><LayersIcon /><span><strong>2D·3D 공간뷰</strong><small>시점별 현장과 비교 위치</small></span><ChevronRightIcon /></button>
          <button type="button" onClick={() => onAction("보고서 화면은 다음 프로토타입 화면에서 이어집니다")}><ReaderIcon /><span><strong>보고서</strong><small>이 현장의 근거와 결정 이력</small></span><ChevronRightIcon /></button>
          <button type="button" onClick={() => onAction("조사 이력 화면은 다음 프로토타입 화면에서 이어집니다")}><TargetIcon /><span><strong>조사·재관측</strong><small>관측 이력과 승인된 후속 조사</small></span><ChevronRightIcon /></button>
        </div>
      </section>

      <button className="ask-entry" type="button" onClick={openAi}><ChatBubbleIcon /><span><strong>이 현장에 질문</strong><small>{site.name}의 검증된 자료에서 답 찾기</small></span><ChevronRightIcon /></button>
    </main>
  );
}

function CaseDetail({ item, decision, onBack, onDecision, openAi }: { item: InsightCase; decision?: Decision; onBack: () => void; onDecision: () => void; openAi: () => void }) {
  const site = getSite(item.siteId);
  return (
    <main className="screen-content detail-screen" data-testid="case-detail">
      <div className="detail-toolbar"><button className="icon-button" type="button" aria-label="안건 목록으로" onClick={onBack}><ArrowLeftIcon /></button><strong>현장 안건</strong><span /></div>
      <header className="case-hero"><div><StatusBadge tone={decision ? "quiet" : item.tone}>{decision === "FIELD_CHECK" ? "담당자 확인 요청됨" : decision === "REVIEWED" ? "검토 완료" : item.status}</StatusBadge><span>{site.name}</span></div><h1>{item.title}</h1><p>{item.claim}</p></header>

      <section className="comparison-preview" aria-label="시점 비교 예시">
        <div><LayersIcon aria-hidden="true" /><span>이전 관측</span><strong>8월 초</strong><em>검증된 공간모델</em></div><ChevronRightIcon aria-hidden="true" /><div><LayersIcon aria-hidden="true" /><span>최근 관측</span><strong>{item.observedAt.split(" ")[0]}</strong><em>검증된 공간모델</em></div><small>합성 데이터의 비교 항목 · 실제 공간 결과 화면 아님</small>
      </section>

      <section className="case-section"><span className="section-kicker">왜 살펴봐야 하나요</span><h2>{item.why}</h2></section>
      <section className="case-section case-section--uncertainty"><span className="section-kicker"><ExclamationTriangleIcon />불확실성과 제한</span><p>{item.uncertainty}</p></section>
      <section className="case-section"><SectionHeading title="판단 근거" /><dl className="evidence-list">{item.evidence.map((evidence) => <div key={evidence.label}><dt>{evidence.label}</dt><dd>{evidence.detail}</dd></div>)}</dl></section>

      <section className="next-step-card"><span className="ai-label"><ActivityLogIcon />KSI AI 제안</span><h2>{item.tone === "attention" ? "현장 담당자에게 누락 구역을 확인하거나, 노트북에서 추가 관측 초안을 검토하세요." : item.tone === "context" ? "현장 담당자에게 실제 공종과 일정 맥락을 요청하세요." : "상대값 사용 제한을 포함해 결과를 검토하세요."}</h2><p>AI는 판단과 승인 대신 근거가 연결된 다음 단계를 제안합니다.</p></section>

      <div className="detail-actions"><button className="button button--primary" type="button" onClick={onDecision}>{decision ? "결정 내용 보기" : "결정 옵션 보기"}</button><button className="button button--outline" type="button" onClick={openAi}>이 안건에 질문</button></div>
    </main>
  );
}

type Message = { id: number; role: "assistant" | "user"; text: string; evidence?: string[] };

function AiScreen({ activeSite, openCase, onPickSite }: { activeSite: Site | null; openCase: (id: string) => void; onPickSite: () => void }) {
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<Message[]>([{ id: 1, role: "assistant", text: "현장 관측과 검증된 분석 결과에서 답을 찾습니다. 근거가 부족하면 모른다고 말할게요." }]);
  const scopeName = activeSite?.name ?? "전체 현장";
  const suggestions = activeSite ? ["이 현장에서 가장 중요한 변화는?", "추가 촬영이 필요한 이유는?", "보고서에 사용할 수 있는 결과는?"] : ["어느 현장을 먼저 살펴봐야 하나요?", "근거가 부족한 현장은 어디인가요?", "최근 상대 물량 변화는 무엇인가요?"];
  const submit = (question: string) => {
    const value = question.trim();
    if (!value) return;
    const lower = value.toLowerCase();
    let answer = "검증된 근거만으로는 그 질문에 답하기 어렵습니다. 현장 일정이나 작업구역 맥락을 먼저 연결해 주세요.";
    let evidence: string[] = [];
    if (lower.includes("먼저") || lower.includes("부족") || lower.includes("촬영")) {
      answer = "서초 복합물류센터를 먼저 살펴보는 것이 좋습니다. 남측 토공 구역의 유효 촬영 범위가 61%라 전체 공정 상태를 대표하기 어렵습니다. 추가 관측은 아직 승인되지 않았습니다.";
      evidence = ["촬영 범위 보고 · 61%", "미관측 셀 · 14개"];
    } else if (lower.includes("물량") || lower.includes("체적")) {
      answer = "인천 자재야적장 A구역의 계산 체적이 이전 관측보다 14% 증가했습니다. 동일 기준면의 상대값이며 계약 정산용 절대 물량은 아닙니다.";
      evidence = ["상대 물량 보고 · +14%", "두 시점 DSM 검증"];
    } else if (lower.includes("변화") || lower.includes("중요")) {
      answer = "김포 제조공장 동측 골조에서 형상 변화가 확인됐습니다. 다만 기준 일정과 WBS가 연결되지 않아 지연이나 완료 여부는 판단할 수 없습니다.";
      evidence = ["3D 시점 비교 · 변화 구역 2곳", "부족한 맥락 · 기준 일정"];
    }
    setMessages((current) => [...current, { id: Date.now(), role: "user", text: value }, { id: Date.now() + 1, role: "assistant", text: answer, evidence }]);
    setDraft("");
  };
  return (
    <main className="screen-content ai-screen" data-testid="ai-screen">
      <PageIntro eyebrow="Grounded AI" title="질문" copy="숫자를 새로 만들지 않고, KSI에 검증된 현장 근거를 찾아 설명합니다." />
      <button className="ai-scope" type="button" onClick={onPickSite}><span><small>질문 범위</small><strong>{scopeName}</strong></span><span>변경<ChevronDownIcon /></span></button>
      <div className="ai-suggestions">{suggestions.map((question) => <button type="button" key={question} onClick={() => submit(question)}>{question}</button>)}</div>
      <section className="ai-conversation" aria-live="polite">
        {messages.map((message) => <div className={`ai-message ai-message--${message.role}`} key={message.id}><span>{message.role === "assistant" ? "KSI AI" : "나"}</span><p>{message.text}</p>{message.evidence?.length ? <button type="button" onClick={() => openCase(message.text.includes("인천") ? "case-volume" : message.text.includes("김포") ? "case-progress" : "case-capture")}><span>{message.evidence.join(" · ")}</span><ChevronRightIcon /></button> : null}</div>)}
      </section>
      <form className="ai-composer" onSubmit={(event) => { event.preventDefault(); submit(draft); }}><KeyboardInput value={draft} onChange={(event) => setDraft(event.target.value)} placeholder={`${scopeName}에 질문하기`} aria-label="현장 근거 질문" /><button type="submit" aria-label="질문 보내기" disabled={!draft.trim()}><PaperPlaneIcon /></button></form>
      <p className="ai-disclaimer">합성 데이터 기반 프로토타입입니다. AI는 비행·승인·계약 수량을 결정하지 않습니다.</p>
    </main>
  );
}

function MoreScreen({ onAction }: { onAction: (message: string) => void }) {
  const groups = [
    { title: "조직 운영", items: [["전체 장비", "조직 보유 장비와 배치 현장"], ["사용자·권한", "구성원과 운영 권한"], ["감사 기록", "결정과 주요 변경 이력"]] },
    { title: "내 환경", items: [["알림 설정", "받을 안건과 전달 방법"], ["앱 설정", "화면과 계정 환경"]] },
    { title: "지원", items: [["운영 지원", "연결 문제와 전문가 복구 경로"]] },
  ];
  return <main className="screen-content" data-testid="more-screen"><PageIntro eyebrow="Organization" title="더보기" copy="특정 현장에 속하지 않는 조직 운영과 개인 설정만 모았습니다." />{groups.map((group) => <section className="menu-group" key={group.title}><h2>{group.title}</h2>{group.items.map(([title, copy]) => <button type="button" key={title} onClick={() => onAction(`${title} 화면은 다음 프로토타입 범위입니다`)}><span><strong>{title}</strong><small>{copy}</small></span><ChevronRightIcon /></button>)}</section>)}</main>;
}

type RemainingSitesVariant = "a" | "b" | "c";
type CandidateSection = "home" | "sites" | "questions" | "notifications" | "more";

const remainingSitesVariantMeta: Record<RemainingSitesVariant, { name: string }> = {
  a: { name: "개별 목록형" },
  b: { name: "최근 업데이트형" },
  c: { name: "요약형" },
};

const candidateNav: Array<{ id: CandidateSection; label: string; icon: ComponentType }> = [
  { id: "home", label: "홈", icon: HomeIcon },
  { id: "sites", label: "현장", icon: DrawingPinIcon },
  { id: "questions", label: "질문", icon: ChatBubbleIcon },
  { id: "notifications", label: "알림", icon: BellIcon },
  { id: "more", label: "더보기", icon: DotsHorizontalIcon },
];

function CandidateSwitcher({ value, onChange }: { value: RemainingSitesVariant; onChange: (value: RemainingSitesVariant) => void }) {
  return (
    <header className="candidate-switcher" aria-label="다른 현장 표현 후보">
      <div>
        <strong>다른 현장 시안 {value.toUpperCase()}</strong>
        <span>{remainingSitesVariantMeta[value].name}</span>
      </div>
      <nav>
        {(["a", "b", "c"] as RemainingSitesVariant[]).map((key) => (
          <button type="button" key={key} className={value === key ? "is-active" : ""} aria-pressed={value === key} onClick={() => onChange(key)}>
            {key.toUpperCase()}
          </button>
        ))}
      </nav>
    </header>
  );
}

function SiteEvidenceFigure({
  src = "/assets/prototype/ksi-synthetic-site-aerial-v1.webp",
  alt = "합성 데이터로 만든 도시 건설 현장 항공 관측 이미지",
  siteName = "서초 복합물류센터",
  observedAt = "8월 22일 관측",
}: {
  src?: string;
  alt?: string;
  siteName?: string;
  observedAt?: string;
}) {
  return (
    <figure className="candidate-photo">
      <img src={src} alt={alt} width="1200" height="751" draggable={false} />
      <figcaption>
        <span>{siteName}</span>
        <strong>{observedAt}</strong>
      </figcaption>
    </figure>
  );
}

const attentionSlides = [
  {
    caseId: "case-capture",
    siteId: "seocho",
    image: "/assets/prototype/ksi-synthetic-site-aerial-v1.webp",
    imageAlt: "합성 데이터로 만든 서초 복합물류센터 건설 현장 항공 관측 이미지",
    observedAt: "8월 22일 관측",
    label: "촬영 근거",
    title: "남측 토공 구역의 촬영 근거가 부족합니다.",
    signal: "판단 가능한 범위 61%",
  },
  {
    caseId: "case-progress",
    siteId: "gimpo",
    image: "/assets/prototype/ksi-synthetic-gimpo-frame-v1.webp",
    imageAlt: "합성 데이터로 만든 김포 제조공장 골조 공사 항공 관측 이미지",
    observedAt: "8월 21일 관측",
    label: "현장 맥락",
    title: "골조 변화의 공정 맥락이 필요합니다.",
    signal: "변화 구역 2곳",
  },
] as const;

const remainingSiteCards = [
  {
    updateId: "update-volume-ready",
    siteId: "incheon",
    image: "/assets/prototype/ksi-synthetic-incheon-yard-v1.webp",
    imageAlt: "합성 데이터로 만든 인천 자재야적장 항공 관측 이미지",
    updateLabel: "새 결과",
    updateTitle: "상대 체적 비교 결과 준비",
    updateDetail: "7월 관측 대비 야적 A구역의 상대 변화 결과를 검토할 수 있습니다. 기준 정보가 연결되기 전까지 절대 물량으로 확정하지 않습니다.",
  },
  {
    updateId: "update-no-new-case",
    siteId: "pangyo",
    image: "/assets/prototype/ksi-synthetic-pangyo-datacenter-v1.webp",
    imageAlt: "합성 데이터로 만든 판교 데이터센터 공사 현장 항공 관측 이미지",
    updateLabel: "최근 관측",
    updateTitle: "새 확인 안건 없음",
    updateDetail: "8월 19일 관측에서 우선 검토가 필요한 변화는 생성되지 않았습니다. 이는 현장 전체의 정상이나 안전을 의미하지 않습니다.",
  },
] as const;

function RemainingSites({ variant, onOpenSites, onOpenUpdate }: { variant: RemainingSitesVariant; onOpenSites: () => void; onOpenUpdate: (updateId: string) => void }) {
  const otherSites = remainingSiteCards.map((item) => ({ ...item, site: getSite(item.siteId) }));
  return (
    <section className={`candidate-remaining candidate-remaining--${variant}`} aria-labelledby="candidate-remaining-heading" data-testid={`candidate-remaining-${variant}`}>
      <div className="candidate-section-heading">
        <h2 id="candidate-remaining-heading">{variant === "b" ? "최근 업데이트" : "다른 현장"}</h2>
        <button type="button" onClick={onOpenSites}>{variant === "b" ? "모두 보기" : "전체 보기"}</button>
      </div>
      {variant === "a" ? (
        <div className="candidate-remaining-list">
          {otherSites.map(({ site }) => (
            <button type="button" key={site.id} onClick={onOpenSites} aria-label={`${site.name}, ${site.observedAt} 관측, ${site.status}`}>
              <i className={`signal signal--${site.tone}`} aria-hidden="true" />
              <span><strong>{site.name}</strong><small>{site.observedAt} 관측 · {site.status}</small></span>
              <ChevronRightIcon aria-hidden="true" />
            </button>
          ))}
        </div>
      ) : variant === "b" ? (
        <div className="candidate-remaining-cards">
          {otherSites.map(({ updateId, site, image, imageAlt, updateLabel, updateTitle }) => (
            <button type="button" key={updateId} onClick={() => onOpenUpdate(updateId)} aria-label={`${site.name}, ${updateLabel}, ${updateTitle}, ${site.observedAt} 관측`}>
              <img src={image} alt={imageAlt} width="1200" height="800" draggable={false} />
              <span><small>{updateLabel} · {site.name}</small><strong>{updateTitle}</strong><em>{site.observedAt} 관측</em></span>
            </button>
          ))}
        </div>
      ) : (
        <button className="candidate-remaining-summary" type="button" onClick={onOpenSites} aria-label="다른 현장 2곳 전체 보기">
          <span className="candidate-remaining-count"><strong>2</strong><small>곳</small></span>
          <span><strong>지금 우선 확인할 안건이 없습니다.</strong><small>인천 8월 20일 · 판교 8월 19일 관측 기준</small></span>
          <ChevronRightIcon aria-hidden="true" />
        </button>
      )}
    </section>
  );
}

function CandidateAHome({ remainingVariant, onOpenEvidence, onAsk, onOpenSites, onOpenUpdate }: { remainingVariant: RemainingSitesVariant; onOpenEvidence: (caseId: string) => void; onAsk: () => void; onOpenSites: () => void; onOpenUpdate: (updateId: string) => void }) {
  const carouselRoot = useRef<HTMLDivElement>(null);
  const [activeSlide, setActiveSlide] = useState(0);

  useEffect(() => {
    const carousel = carouselRoot.current?.querySelector<HTMLElement>(".mobile-carousel");
    if (!carousel) return;
    let settleTimer: number | null = null;
    const getSlides = () => Array.from(carousel.querySelectorAll<HTMLElement>(".candidate-attention-slide"));
    const getNearestSlide = () => {
      const slides = getSlides();
      if (!slides.length) return 0;
      return slides.reduce((best, slide, index) => (
        Math.abs(slide.offsetLeft - carousel.scrollLeft) < Math.abs(slides[best].offsetLeft - carousel.scrollLeft) ? index : best
      ), 0);
    };
    const updateActiveSlide = () => {
      const nearest = getNearestSlide();
      setActiveSlide(nearest);
      if (settleTimer !== null) window.clearTimeout(settleTimer);
      settleTimer = window.setTimeout(() => {
        const settledIndex = getNearestSlide();
        const target = getSlides()[settledIndex];
        if (target && Math.abs(target.offsetLeft - carousel.scrollLeft) > 1) {
          carousel.scrollTo({ left: target.offsetLeft, behavior: "smooth" });
        }
      }, 140);
    };
    carousel.addEventListener("scroll", updateActiveSlide, { passive: true });
    updateActiveSlide();
    return () => {
      carousel.removeEventListener("scroll", updateActiveSlide);
      if (settleTimer !== null) window.clearTimeout(settleTimer);
    };
  }, []);

  const goToSlide = (index: number) => {
    const carousel = carouselRoot.current?.querySelector<HTMLElement>(".mobile-carousel");
    const slides = carousel ? Array.from(carousel.querySelectorAll<HTMLElement>(".candidate-attention-slide")) : [];
    const target = slides[index];
    if (!carousel || !target) return;
    carousel.scrollTo({ left: target.offsetLeft, behavior: "smooth" });
    setActiveSlide(index);
  };

  return (
    <main className="candidate-home candidate-home--a" data-testid="candidate-home-a">
      <h1 className="candidate-a-summary" aria-label="전체 4곳 · 확인 필요 2곳"><span>전체 4곳</span><i aria-hidden="true">·</i><em>확인 필요 2곳</em></h1>
      <section className="candidate-attention" aria-labelledby="candidate-attention-heading">
        <div className="candidate-attention-heading">
          <h2 id="candidate-attention-heading">확인이 필요한 현장</h2>
          <div>
            <button type="button" aria-label="이전 현장" disabled={activeSlide === 0} onClick={() => goToSlide(activeSlide - 1)}><ArrowLeftIcon /></button>
            <button type="button" aria-label="다음 현장" disabled={activeSlide === attentionSlides.length - 1} onClick={() => goToSlide(activeSlide + 1)}><ChevronRightIcon /></button>
          </div>
        </div>
        <div ref={carouselRoot}>
          <Carousel className="candidate-attention-carousel" contentClassName="candidate-attention-track" ariaLabel="확인 필요 현장 캐러셀">
            {attentionSlides.map((slide) => (
              <button className="candidate-attention-slide" type="button" key={slide.caseId} onClick={() => onOpenEvidence(slide.caseId)} aria-label={`${getSite(slide.siteId).name}, ${slide.title}`}>
                <SiteEvidenceFigure src={slide.image} alt={slide.imageAlt} siteName={getSite(slide.siteId).name} observedAt={slide.observedAt} />
                <span className="candidate-hero-copy">
                  <small>{slide.label}</small>
                  <strong>{slide.title}</strong>
                  <span>{slide.signal} <ChevronRightIcon /></span>
                </span>
              </button>
            ))}
          </Carousel>
        </div>
        <div className="candidate-attention-pagination" aria-label={`확인 필요 현장 ${activeSlide + 1} / ${attentionSlides.length}`}>
          <div>
            {attentionSlides.map((slide, index) => <button type="button" key={slide.caseId} className={activeSlide === index ? "is-active" : ""} aria-label={`${index + 1}번째 현장 보기`} aria-current={activeSlide === index ? "true" : undefined} onClick={() => goToSlide(index)}><i /></button>)}
          </div>
          <strong aria-live="polite">{getSite(attentionSlides[activeSlide].siteId).name}</strong>
          <span>{activeSlide + 1} / {attentionSlides.length}</span>
        </div>
      </section>
      <RemainingSites variant={remainingVariant} onOpenSites={onOpenSites} onOpenUpdate={onOpenUpdate} />
      <button className="candidate-ask" type="button" onClick={onAsk}>
        <ChatBubbleIcon aria-hidden="true" />
        <span><strong>왜 먼저 봐야 하나요?</strong><small>현장 근거로 KSI에 질문하기</small></span>
        <ChevronRightIcon aria-hidden="true" />
      </button>
    </main>
  );
}

function CandidateSectionScreen({ section, onOpenEvidence, onHome }: { section: CandidateSection; onOpenEvidence: () => void; onHome: () => void }) {
  if (section === "questions") {
    return (
      <main className="candidate-section-screen" data-testid="candidate-questions">
        <span>검증된 현장 근거</span>
        <h1>무엇이 궁금한가요?</h1>
        <p>AI는 관측 결과를 설명하고 부족한 맥락을 알려줍니다. 승인이나 비행은 대신하지 않습니다.</p>
        <button className="question-suggestion" type="button" onClick={onOpenEvidence}>왜 서초 현장을 먼저 봐야 하나요?<ChevronRightIcon /></button>
        <button className="question-suggestion" type="button" onClick={onOpenEvidence}>이번 주 가장 큰 변화는 무엇인가요?<ChevronRightIcon /></button>
      </main>
    );
  }
  if (section === "sites") {
    return (
      <main className="candidate-section-screen" data-testid="candidate-sites">
        <span>4개 운영 현장</span>
        <h1>현장</h1>
        <div className="candidate-site-list">
          {sites.map((site) => <button type="button" key={site.id} onClick={site.id === "seocho" ? onOpenEvidence : onHome}><i className={`signal signal--${site.tone}`} /><span><strong>{site.name}</strong><small>{site.status}</small></span><ChevronRightIcon /></button>)}
        </div>
      </main>
    );
  }
  return (
    <main className="candidate-section-screen" data-testid={`candidate-${section}`}>
      <span>홈 구조 비교용 시안</span>
      <h1>{section === "notifications" ? "알림" : "더보기"}</h1>
      <p>{section === "notifications" ? "새로운 결과와 사용자에게 필요한 확인만 모아 전달합니다." : "조직 설정, 사용자 권한과 운영 지원은 이곳에서 관리합니다."}</p>
      <button className="button--primary candidate-return" type="button" onClick={onHome}>홈으로 돌아가기</button>
    </main>
  );
}

function CandidateBottomNav({ active, onChange }: { active: CandidateSection; onChange: (section: CandidateSection) => void }) {
  return (
    <nav className="candidate-bottom-nav" aria-label="후보 주요 메뉴">
      {candidateNav.map((item) => { const Icon = item.icon; return (
        <button type="button" key={item.id} className={active === item.id ? "is-active" : ""} aria-current={active === item.id ? "page" : undefined} onClick={() => onChange(item.id)}>
          <Icon aria-hidden="true" /><span>{item.label}</span>
        </button>
      ); })}
    </nav>
  );
}

function HomeCandidates() {
  const [remainingVariant, setRemainingVariant] = useState<RemainingSitesVariant>("a");
  const [section, setSection] = useState<CandidateSection>("home");
  const [sheet, setSheet] = useState<"none" | "evidence" | "answer" | "update">("none");
  const [evidenceCaseId, setEvidenceCaseId] = useState("case-capture");
  const [updateId, setUpdateId] = useState<(typeof remainingSiteCards)[number]["updateId"]>("update-volume-ready");
  const evidenceCase = getCase(evidenceCaseId);
  const evidenceSite = getSite(evidenceCase.siteId);
  const activeUpdate = remainingSiteCards.find((item) => item.updateId === updateId) ?? remainingSiteCards[0];
  const activeUpdateSite = getSite(activeUpdate.siteId);

  const openCandidateEvidence = (caseId = "case-capture") => {
    setEvidenceCaseId(caseId);
    setSheet("evidence");
  };

  const openRecentUpdate = (nextUpdateId: string) => {
    const nextUpdate = remainingSiteCards.find((item) => item.updateId === nextUpdateId);
    if (!nextUpdate) return;
    setUpdateId(nextUpdate.updateId);
    setSheet("update");
  };

  let content: ReactNode;
  if (section !== "home") content = <CandidateSectionScreen section={section} onOpenEvidence={() => openCandidateEvidence()} onHome={() => setSection("home")} />;
  else content = <CandidateAHome remainingVariant={remainingVariant} onOpenEvidence={openCandidateEvidence} onAsk={() => { setEvidenceCaseId("case-capture"); setSheet("answer"); }} onOpenSites={() => setSection("sites")} onOpenUpdate={openRecentUpdate} />;

  return (
    <div className="prototype-app candidate-app" data-testid="home-candidates">
      <CandidateSwitcher value={remainingVariant} onChange={setRemainingVariant} />
      <MobileScroll className="candidate-scroll">{content}</MobileScroll>
      <CandidateBottomNav active={section} onChange={setSection} />
      <BottomSheet open={sheet === "evidence"} onOpenChange={(open) => setSheet(open ? "evidence" : "none")} title={evidenceSite.name} description={`${evidenceCase.observedAt} · ${evidenceCase.category}`} snap={0.7}>
        <div className="candidate-evidence-sheet">
          <strong>{evidenceCase.claim}</strong>
          <p>{evidenceCase.uncertainty}</p>
          <dl><div><dt>핵심 신호</dt><dd>{evidenceCase.signal}</dd></div><div><dt>판단 근거</dt><dd>{evidenceCase.evidence[0].detail}</dd></div><div><dt>업무 영향</dt><dd>맥락 확인 전 확정 불가</dd></div></dl>
          <button type="button" onClick={() => setSheet("answer")}>KSI에 이 변화 묻기 <ChevronRightIcon /></button>
        </div>
      </BottomSheet>
      <BottomSheet open={sheet === "answer"} onOpenChange={(open) => setSheet(open ? "answer" : "none")} title="KSI의 설명" description="촬영 범위 보고와 원본 계보를 근거로 답합니다." snap={0.64}>
        <div className="candidate-answer-sheet">
          <ChatBubbleIcon />
          <p>{evidenceCase.why} {evidenceCase.uncertainty}</p>
          <small>근거 · {evidenceCase.evidence.map((item) => item.detail).join(" · ")}</small>
        </div>
      </BottomSheet>
      <BottomSheet open={sheet === "update"} onOpenChange={(open) => setSheet(open ? "update" : "none")} title={activeUpdateSite.name} description={`${activeUpdateSite.observedAt} 관측 · ${activeUpdate.updateLabel}`} snap={0.62}>
        <div className="candidate-update-sheet">
          <span>{activeUpdate.updateLabel}</span>
          <strong>{activeUpdate.updateTitle}</strong>
          <p>{activeUpdate.updateDetail}</p>
          <small>합성 관측 데이터로 구성한 제품 시안입니다.</small>
          <button type="button" onClick={() => { setSheet("none"); setSection("sites"); }}>현장 화면에서 보기 <ChevronRightIcon /></button>
        </div>
      </BottomSheet>
      <span className="prototype-label">HTML DESIGN STUDY · SYNTHETIC DATA</span>
    </div>
  );
}

const navItems: Array<{ id: NavView; label: string; icon: ComponentType }> = [
  { id: "home", label: "홈", icon: HomeIcon },
  { id: "sites", label: "현장", icon: DrawingPinIcon },
  { id: "cases", label: "안건", icon: ReaderIcon },
  { id: "ai", label: "질문", icon: ChatBubbleIcon },
  { id: "more", label: "더보기", icon: DotsHorizontalIcon },
];

function LegacyPrototype() {
  const [view, setView] = useState<View>("home");
  const [activeSiteId, setActiveSiteId] = useState<string | null>(null);
  const [activeCaseId, setActiveCaseId] = useState("case-capture");
  const [sheet, setSheet] = useState<Sheet>("none");
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [toast, setToast] = useState<string | null>(null);
  const toastTimer = useRef<number | null>(null);
  const activeSite = useMemo(() => activeSiteId ? getSite(activeSiteId) : null, [activeSiteId]);
  const activeCase = useMemo(() => getCase(activeCaseId), [activeCaseId]);

  const showToast = (message: string) => {
    setToast(message);
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 2800);
  };
  const openSite = (siteId: string) => { setActiveSiteId(siteId); setSheet("none"); setView("site"); };
  const openCase = (caseId: string) => { setActiveCaseId(caseId); setSheet("none"); setView("case-detail"); };
  const openAi = (siteId?: string) => { if (siteId) setActiveSiteId(siteId); setView("ai"); };
  const saveDecision = (decision: Decision) => {
    setDecisions((current) => ({ ...current, [activeCaseId]: decision }));
    setSheet("none");
    showToast(decision === "FIELD_CHECK" ? "현장 담당자 확인 요청을 기록했습니다" : "안건을 검토 완료로 정리했습니다");
  };
  const activeNav: NavView = view === "site" ? "sites" : view === "case-detail" ? "cases" : view;

  let content: ReactNode;
  if (view === "home") content = <PortfolioHome decisions={decisions} openCase={openCase} openCases={() => setView("cases")} openSites={() => setView("sites")} openAi={() => openAi()} />;
  else if (view === "sites") content = <SiteList openSite={openSite} />;
  else if (view === "cases") content = <CaseList decisions={decisions} openCase={openCase} />;
  else if (view === "site" && activeSite) content = <SiteHome site={activeSite} decisions={decisions} onBack={() => setView("sites")} onPickSite={() => setSheet("sites")} openCase={openCase} openAi={() => openAi(activeSite.id)} onAction={showToast} />;
  else if (view === "case-detail") content = <CaseDetail item={activeCase} decision={decisions[activeCase.id]} onBack={() => setView("cases")} onDecision={() => setSheet("decision")} openAi={() => openAi(activeCase.siteId)} />;
  else if (view === "ai") content = <AiScreen activeSite={activeSite} openCase={openCase} onPickSite={() => setSheet("sites")} />;
  else content = <MoreScreen onAction={showToast} />;

  const unresolved = cases.filter((item) => item.tone !== "ready" && !decisions[item.id]).length;
  return (
    <div className="prototype-app">
      <AppTopbar onHome={() => setView("home")} onNotifications={() => setSheet("notifications")} hasUnread={unresolved > 0} />
      <MobileScroll className="app-screen">{content}</MobileScroll>
      <nav className="bottom-nav" aria-label="주요 메뉴">
        {navItems.map((item) => { const Icon = item.icon; return <button type="button" key={item.id} className={activeNav === item.id ? "is-active" : ""} aria-current={activeNav === item.id ? "page" : undefined} onClick={() => setView(item.id)}><Icon /><span>{item.label}</span>{item.id === "cases" && unresolved > 0 ? <i aria-label={`새 안건 ${unresolved}건`} /> : null}</button>; })}
      </nav>
      <span className="prototype-label">DESIGN PROTOTYPE · SYNTHETIC DATA</span>
      {toast ? <div className="prototype-toast" role="status">{toast}</div> : null}

      <BottomSheet open={sheet === "sites"} onOpenChange={(open) => setSheet(open ? "sites" : "none")} title="질문할 현장 선택" description="현장을 선택하면 해당 현장의 자료와 안건으로 범위를 좁힙니다." snap={0.62}>
        <div className="sheet-list"><button type="button" className={activeSiteId === null ? "is-selected" : ""} onClick={() => { setActiveSiteId(null); setSheet("none"); setView("ai"); }}><span><strong>전체 현장</strong><small>4개 현장의 검증된 결과</small></span><ChevronRightIcon /></button>{sites.map((site) => <button type="button" key={site.id} className={site.id === activeSiteId ? "is-selected" : ""} onClick={() => { setActiveSiteId(site.id); setSheet("none"); setView(view === "site" ? "site" : "ai"); }}><span><strong>{site.name}</strong><small>{site.location}</small></span><StatusBadge tone={site.tone}>{site.status}</StatusBadge></button>)}</div>
      </BottomSheet>

      <BottomSheet open={sheet === "notifications"} onOpenChange={(open) => setSheet(open ? "notifications" : "none")} title="새 현장 안건" description="현장과 근거 상태를 함께 표시합니다." snap={0.52}>
        <div className="sheet-list">{cases.filter((item) => !decisions[item.id]).slice(0, 2).map((item) => <button type="button" key={item.id} onClick={() => openCase(item.id)}><StatusBadge tone={item.tone}>{item.status}</StatusBadge><span><strong>{getSite(item.siteId).name}</strong><small>{item.title}</small></span><ChevronRightIcon /></button>)}</div>
      </BottomSheet>

      <BottomSheet open={sheet === "decision"} onOpenChange={(open) => setSheet(open ? "decision" : "none")} title="이 안건의 다음 단계" description={`${getSite(activeCase.siteId).name} · 결정은 사용자와 시각이 함께 기록됩니다.`} snap={0.68}>
        <div className="decision-sheet">
          {decisions[activeCase.id] ? <div className="current-decision"><CheckCircledIcon /><span><strong>{decisions[activeCase.id] === "FIELD_CHECK" ? "현장 담당자 확인 요청됨" : "검토 완료"}</strong><small>이 프로토타입 세션에서 기록한 결정입니다.</small></span></div> : null}
          <button className="decision-option" type="button" onClick={() => saveDecision("FIELD_CHECK")}><TargetIcon /><span><strong>현장 담당자에게 확인 요청</strong><small>공종·일정 또는 누락 구역의 실제 맥락을 요청합니다.</small></span><ChevronRightIcon /></button>
          <button className="decision-option" type="button" onClick={() => saveDecision("REVIEWED")}><CheckCircledIcon /><span><strong>검토 완료로 정리</strong><small>근거와 사용 제한을 확인한 안건으로 기록합니다.</small></span><ChevronRightIcon /></button>
          <button className="decision-option decision-option--desktop" type="button" onClick={() => showToast("추가 관측 초안 검토는 노트북에서 이어집니다")}><CubeIcon /><span><strong>추가 관측 초안 검토</strong><small>관측 범위와 Mission 발급에 영향을 주므로 노트북에서 진행합니다.</small></span><ChevronRightIcon /></button>
        </div>
      </BottomSheet>
    </div>
  );
}

export default function Prototype() {
  const showLegacy = new URLSearchParams(window.location.search).get("legacy") === "1";
  return showLegacy ? <LegacyPrototype /> : <HomeCandidates />;
}
