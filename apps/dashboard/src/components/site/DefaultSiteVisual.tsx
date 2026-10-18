export interface DefaultSiteVisualProps {
  /** 같은 현장이 늘 같은 모양을 갖도록 하는 씨앗 — 보통 siteId. */
  seed: string;
  /**
   * 화면에 이 표시를 설명하는 문구가 따로 있을 때는 넘기지 않는다 — 그러면 순수
   * 장식(aria-hidden)이 되어 스크린리더가 같은 말을 두 번 읽지 않는다. 문구가 없을
   * 때만 이름을 준다.
   */
  label?: string;
  className?: string;
}

function seedValue(seed: string): number {
  return [...seed].reduce((sum, character) => sum + character.charCodeAt(0), 0);
}

/**
 * 관측 이미지가 없을 때 **기본으로 적용되는 표시**.
 *
 * 등록된 관측 이미지가 없으면 빈 칸 대신 이 장식을 쓴다. 다만 지도·차트처럼
 * 보이는 것은 쓰지 않는다 — 격자·경계 폴리곤·측정점은 데이터로 오인되기 쉽다
 * (감사 P2-1). 여기서는 완만한 등고선 띠만 두고, 무엇을 보고 있는지는
 * 바깥의 문구가 말한다. 씨앗에 따라 띠의 흐름만 조금씩 달라진다.
 */
export function DefaultSiteVisual({ seed, label, className = "" }: DefaultSiteVisualProps) {
  const variant = seedValue(seed) % 3;
  const phases = [
    { a: "M-40 232c96-38 168-96 262-104 92-8 170 40 300 8", b: "M-40 300c118-30 196-104 302-108 100-4 168 48 300 20", c: "M-40 372c132-24 210-116 330-112 96 4 150 56 290 34" },
    { a: "M-40 196c110-44 150-104 258-96 96 8 176 60 306 20", b: "M-40 268c124-36 178-112 296-100 104 10 156 62 292 24", c: "M-40 344c140-28 196-120 322-104 92 12 148 60 288 28" },
    { a: "M-40 214c88-52 178-84 268-84 104 0 164 56 296 12", b: "M-40 286c112-40 186-108 300-96 98 10 158 58 296 24", c: "M-40 360c126-32 204-124 328-108 90 12 152 62 286 30" },
  ][variant];

  return (
    <div
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      className={`relative isolate overflow-hidden bg-sunk ${className}`}
    >
      <svg aria-hidden="true" viewBox="0 0 560 400" preserveAspectRatio="xMidYMid slice" className="absolute inset-0 size-full">
        <rect width="560" height="400" fill="var(--sunk)" />
        {/* 완만한 등고선 띠 — 축·격자·측정점 없이 흐름만 남긴다. */}
        <path d={phases.a} fill="none" stroke="var(--line-strong)" strokeWidth="46" strokeLinecap="round" opacity="0.22" />
        <path d={phases.b} fill="none" stroke="var(--line-strong)" strokeWidth="34" strokeLinecap="round" opacity="0.16" />
        <path d={phases.c} fill="none" stroke="var(--line-strong)" strokeWidth="24" strokeLinecap="round" opacity="0.12" />
        <path d={phases.a} fill="none" stroke="var(--surface)" strokeWidth="2" opacity="0.55" />
        <path d={phases.b} fill="none" stroke="var(--surface)" strokeWidth="2" opacity="0.4" />
      </svg>
    </div>
  );
}
