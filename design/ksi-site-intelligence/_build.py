#!/usr/bin/env python3
"""KSI 현장 지능 — 화면 시안을 브랜드 방향별로 생성한다.

레이아웃·정보위계·카피는 방향 간에 **완전히 동일**하고 팔레트만 다르다 — 그래야 대표자가
보는 차이가 순수하게 '브랜드 색 방향'이 된다(다른 변수가 섞이면 비교가 아니라 취향투표가 된다).

    python3 design/ksi-site-intelligence/_build.py

생성물:
    screens/<화면>-<방향>.html      브랜드 비교용 (3화면 × 3방향)
    studies/sort-order.html         정렬 기준 비교 (방향 A 고정, 정렬만 3가지)
"""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).parent

# ═══════════════════════════════════════════════════════════════════════════
# 브랜드 방향 — 액센트와 '선택된 뉴트럴'만 다르다.
# 안전 상태색(위험/높음/보통/안전)은 세 방향 모두 동일하게 고정한다: 비교의 통제 변수이자,
# 안전 크리티컬 UI에서 의미색은 브랜드가 바뀐다고 따라 바뀌면 안 되는 값이다.
# ═══════════════════════════════════════════════════════════════════════════
DIRECTIONS = [
    {
        "slug": "a-survey-teal",
        "name": "계측 청록",
        "en": "Survey Teal",
        "thesis": "측량 계측기·수준기의 세계. 액센트가 안전 상태색에서 가장 멀다.",
        "tokens": {
            "accent": "#0C6E7A",
            "accent-hover": "#095760",
            "accent-tint": "#E2F1F2",
            "accent-ink": "#06454D",
            "accent-on": "#FFFFFF",
            # 뉴트럴을 액센트 쪽으로 살짝 편향 — 순수 회색은 '고르지 않은' 인상을 준다
            "page": "#F4F8F8",
            "surface": "#FFFFFF",
            "sunk": "#EBF1F2",
            "line": "#D9E4E5",
            "line-strong": "#B9CACC",
            "text-1": "#0E2124",
            "text-2": "#47595C",
            "text-muted": "#7F9295",
            "sidebar": "#0B2B30",
            "sidebar-text": "#CFE3E5",
            "sidebar-muted": "#7EA3A8",
        },
    },
    {
        "slug": "b-blueprint-navy",
        "name": "도면 남색",
        "en": "Blueprint Navy",
        "thesis": "건축 도면과 좌표계의 세계. 신뢰·정밀을 색으로 말한다.",
        "tokens": {
            "accent": "#1B3A6B",
            "accent-hover": "#142D55",
            "accent-tint": "#E8EDF6",
            "accent-ink": "#122748",
            "accent-on": "#FFFFFF",
            "page": "#F5F7FA",
            "surface": "#FFFFFF",
            "sunk": "#ECEFF5",
            "line": "#DCE2EC",
            "line-strong": "#BAC5D6",
            "text-1": "#111A2B",
            "text-2": "#4A5568",
            "text-muted": "#828DA3",
            "sidebar": "#121F38",
            "sidebar-text": "#D3DCEC",
            "sidebar-muted": "#8494B0",
        },
    },
    {
        "slug": "c-ksi-orange",
        "name": "KSI 오렌지 (현행)",
        "en": "KSI Orange",
        "thesis": "기존 Scout 시스템 상속. 비교 기준선 — 액센트가 '주의'와 인접한 게 보인다.",
        "tokens": {
            "accent": "#F97316",
            "accent-hover": "#EA6C0A",
            "accent-tint": "#FFF3E8",
            "accent-ink": "#9A4406",
            "accent-on": "#FFFFFF",
            "page": "#FAF9F7",
            "surface": "#FFFFFF",
            "sunk": "#F3F1ED",
            "line": "#E6E2DB",
            "line-strong": "#CBC4B8",
            "text-1": "#211C15",
            "text-2": "#57503F",
            "text-muted": "#918876",
            "sidebar": "#2A2118",
            "sidebar-text": "#E6DED2",
            "sidebar-muted": "#A79B88",
        },
    },
    {
        "slug": "d-ink-mono",
        "name": "잉크 모노크롬",
        "en": "Ink Mono",
        "thesis": "색을 브랜드에 쓰지 않는다. 화면에서 색이 있는 곳은 오직 안전 상태뿐 — 가장 극단적인 의미 분리.",
        "tokens": {
            "accent": "#1F2124",
            "accent-hover": "#0E0F11",
            "accent-tint": "#EDEEF0",
            "accent-ink": "#1F2124",
            "accent-on": "#FFFFFF",
            "page": "#F6F7F8",
            "surface": "#FFFFFF",
            "sunk": "#EDEEF0",
            "line": "#E0E2E5",
            "line-strong": "#BFC3C8",
            "text-1": "#121417",
            "text-2": "#4E5359",
            "text-muted": "#878D94",
            "sidebar": "#16181A",
            "sidebar-text": "#DDE0E3",
            "sidebar-muted": "#8B9197",
        },
    },
    {
        "slug": "e-steel-slate",
        "name": "스틸 슬레이트",
        "en": "Steel Slate",
        "thesis": "강재·비계·중장비의 색. 현장 자재에서 그대로 가져왔고, 상태색과 온도가 겹치지 않는다.",
        "tokens": {
            "accent": "#3E5866",
            "accent-hover": "#31474F",
            "accent-tint": "#E9EEF1",
            "accent-ink": "#263A45",
            "accent-on": "#FFFFFF",
            "page": "#F5F7F8",
            "surface": "#FFFFFF",
            "sunk": "#EBEFF1",
            "line": "#DCE2E5",
            "line-strong": "#BAC4CA",
            "text-1": "#111A1F",
            "text-2": "#485762",
            "text-muted": "#83919A",
            "sidebar": "#1E2C34",
            "sidebar-text": "#D4DDE2",
            "sidebar-muted": "#87979F",
        },
    },
    {
        "slug": "f-indigo",
        "name": "인디고",
        "en": "Indigo",
        "thesis": "현대 소프트웨어의 색. 상태색 어디와도 겹치지 않고 제품이 '현장 장비'보다 '도구'로 읽힌다.",
        "tokens": {
            "accent": "#4338CA",
            "accent-hover": "#372DA8",
            "accent-tint": "#EDECFB",
            "accent-ink": "#2E2688",
            "accent-on": "#FFFFFF",
            "page": "#F7F7FB",
            "surface": "#FFFFFF",
            "sunk": "#EFEFF6",
            "line": "#E1E1EC",
            "line-strong": "#C1C1D6",
            "text-1": "#15142B",
            "text-2": "#4C4A66",
            "text-muted": "#87859E",
            "sidebar": "#1E1B4B",
            "sidebar-text": "#D9D7EE",
            "sidebar-muted": "#8D8AB4",
        },
    },
    {
        "slug": "g-khaki-olive",
        "name": "카키 올리브",
        "en": "Khaki Olive",
        "thesis": "지반·흙·측량 표식의 색. 회사 이름(KhakiSkech)에 이미 들어 있는 색이기도 하다.",
        "tokens": {
            "accent": "#4F5B3C",
            "accent-hover": "#3E4830",
            "accent-tint": "#EFF1E7",
            "accent-ink": "#333C26",
            "accent-on": "#FFFFFF",
            "page": "#F7F8F3",
            "surface": "#FFFFFF",
            "sunk": "#EEF0E7",
            "line": "#E1E4D8",
            "line-strong": "#C2C7B4",
            "text-1": "#191C13",
            "text-2": "#4F5445",
            "text-muted": "#8A8F7C",
            "sidebar": "#242819",
            "sidebar-text": "#DEE2D3",
            "sidebar-muted": "#8F9680",
        },
    },
    # ── 카키(#C3B091) 계열 ─────────────────────────────────────────────────
    # 대표자 지목색. 페르시아어 khāk(흙·먼지)에서 온 색이고 사명(KhakiSkech)과 연결된다.
    # 다만 밝아서(상대휘도 ~0.47) 흰 배경 위 텍스트로는 대비가 2.1:1 밖에 안 나온다.
    # 그래서 세 안의 차이는 '카키를 어느 자리에 쓰는가'다:
    #   H  표식과 서피스 온기에만 (액센트는 잉크)
    #   I  액센트 자체로 (배경으로 쓰고 그 위 글자를 어둡게)
    #   J  깊게 눌러서 액센트로 (흰 글자가 얹히는 흙빛)
    {
        "slug": "h-ink-khaki",
        "name": "잉크 + 카키 표식",
        "en": "Ink & Khaki",
        "finalist": True,
        "thesis": "액센트는 잉크로 두어 색을 의미에만 남기고, 카키는 로고 표식과 종이 온기로만 쓴다.",
        "tokens": {
            "accent": "#1F2124",
            "accent-hover": "#0E0F11",
            "accent-tint": "#EFEAE0",
            "accent-ink": "#1F2124",
            "accent-on": "#FFFFFF",
            "brand": "#C3B091",
            "brand-on": "#2A2318",
            "page": "#F8F6F1",
            "surface": "#FFFFFF",
            "sunk": "#F1EDE4",
            "line": "#E5E0D4",
            "line-strong": "#C7C0AF",
            "text-1": "#1A1712",
            "text-2": "#54503F",
            "text-muted": "#8D8873",
            "sidebar": "#2A2620",
            "sidebar-text": "#E3DCCB",
            "sidebar-muted": "#9C937C",
        },
    },
    {
        "slug": "i-khaki-dust",
        "name": "카키 — 흙과 먼지",
        "en": "Khaki Dust",
        "finalist": True,
        "thesis": "#C3B091을 액센트 그대로. 버튼 위 글자를 어둡게 얹어 대비를 얻고, 링크용으로만 눌러 쓴다.",
        "tokens": {
            "accent": "#C3B091",
            "accent-hover": "#B09C79",
            "accent-tint": "#F3EEE4",
            "accent-ink": "#5F4D2E",
            # 흰 배경 위 텍스트 전용 — #C3B091 자체는 2.1:1 이라 본문 링크에 못 쓴다
            "accent-text": "#7A6541",
            "accent-on": "#2A2318",
            "brand": "#C3B091",
            "brand-on": "#2A2318",
            "page": "#F8F6F1",
            "surface": "#FFFFFF",
            "sunk": "#F1EDE4",
            "line": "#E5E0D4",
            "line-strong": "#C8C1B0",
            "text-1": "#1C1913",
            "text-2": "#565040",
            "text-muted": "#8F8974",
            "sidebar": "#2E2820",
            "sidebar-text": "#E6DFCE",
            "sidebar-muted": "#A0977F",
        },
    },
    {
        "slug": "j-khaki-deep",
        "name": "카키 — 깊은 흙",
        "en": "Khaki Deep",
        "finalist": True,
        "thesis": "같은 흙색을 눌러 쓴다. 흰 글자가 얹히므로 대비 예외 없이 어디에나 쓸 수 있다.",
        "tokens": {
            "accent": "#7A6541",
            "accent-hover": "#63512F",
            "accent-tint": "#F1ECE1",
            "accent-ink": "#4E3F26",
            "accent-on": "#FFFFFF",
            "brand": "#C3B091",
            "brand-on": "#2A2318",
            "page": "#F8F6F1",
            "surface": "#FFFFFF",
            "sunk": "#F1EDE4",
            "line": "#E5E0D4",
            "line-strong": "#C8C1B0",
            "text-1": "#1C1913",
            "text-2": "#565040",
            "text-muted": "#8F8974",
            "sidebar": "#2B2519",
            "sidebar-text": "#E6DFCE",
            "sidebar-muted": "#A0977F",
        },
    },
]

# 대표자가 좁힌 후보 — 잉크 계열과 카키 계열. 나머지는 이전 검토안으로 남긴다.
for _d in DIRECTIONS:
    if _d["slug"] == "d-ink-mono":
        _d["finalist"] = True
    _d.setdefault("finalist", False)

# 안전 상태색 — 세 방향 공통 (통제 변수)
SAFETY = {
    "crit": "#C42B22",
    "crit-bg": "#FDECEA",
    "crit-ink": "#8A1C16",
    "high": "#B26A06",
    "high-bg": "#FCF1DC",
    "high-ink": "#7A4804",
    "mid": "#1F6FB8",
    "mid-bg": "#E7F0FA",
    "mid-ink": "#134676",
    "safe": "#157F4B",
    "safe-bg": "#E3F3EA",
    "safe-ink": "#0C5231",
    "idle": "#78848A",
    "idle-bg": "#EFF2F3",
}

# ═══════════════════════════════════════════════════════════════════════════
# 전 화면 공통 CSS — 셸·타이포·배지·버튼
# ═══════════════════════════════════════════════════════════════════════════
BASE_CSS = """
  *, *::before, *::after { box-sizing: border-box; }
  html { -webkit-text-size-adjust: 100%; }
  body {
    margin: 0;
    background: var(--page);
    color: var(--text-1);
    font-family: 'Pretendard Variable', Pretendard, -apple-system, BlinkMacSystemFont,
                 'Apple SD Gothic Neo', 'Noto Sans KR', 'Malgun Gothic', system-ui, sans-serif;
    font-size: 14px;
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
    word-break: keep-all;
  }
  /* 숫자·시각·좌표는 계측 제품의 주인공이다 — 본문과 다른 얼굴을 준다 */
  .num {
    font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, 'Cascadia Mono',
                 Menlo, Consolas, monospace;
    font-variant-numeric: tabular-nums;
    font-feature-settings: 'tnum' 1;
  }
  :focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 3px; }

  /* ── 뷰포트 전제 ────────────────────────────────────────────────────────
     주 사용처는 **태블릿 가로(1024~)와 데스크톱**이다. 현장에서는 태블릿,
     사무실에서는 데스크톱 — 3D 모델·정사영상·구역 설정처럼 이 제품이 다루는 것들이
     세로 화면에 들어가지 않기 때문이다.

     그래서 브레이크포인트를 '데스크톱에 모바일 대응을 붙이는' 순서가 아니라
     **1024를 1급 레이아웃으로 두고** 잡는다:
       1280+   사이드바 216 · 상세 396   (데스크톱)
       1024~   사이드바 176 · 상세 340   (태블릿 가로 — 마스터·디테일 유지)
       ~1000   1열로 접힘               (태블릿 세로·폰 — 보조 경로)
     1024에서 마스터·디테일이 깨지면 현장에서 목록과 상세를 오가야 해서
     트리아지 한 건당 왕복이 두 번씩 늘어난다. */
  .shell { display: grid; grid-template-columns: 216px 1fr; min-height: 100vh; }
  @media (max-width: 1279px) { .shell { grid-template-columns: 176px 1fr; } }

  .side { background: var(--sidebar); color: var(--sidebar-text); padding: 18px 0 24px; }
  .brand { display: flex; align-items: center; gap: 9px; padding: 0 18px 22px; }
  /* 로고 표식만 --brand 를 쓴다. 액센트를 무채색으로 두고도 브랜드 색을 남길 수 있게
     분리한 토큰이다 — 미정의 방향에서는 액센트로 떨어진다. */
  .brand-mark {
    width: 26px; height: 26px; flex: none; border-radius: 6px;
    background: var(--brand, var(--accent)); color: var(--brand-on, var(--accent-on));
    display: grid; place-items: center; font-size: 12px; font-weight: 800; letter-spacing: -0.03em;
  }
  .brand-name { font-size: 13.5px; font-weight: 700; letter-spacing: -0.01em; }
  .brand-sub { font-size: 10.5px; color: var(--sidebar-muted); letter-spacing: 0.04em; }
  .nav-group { padding: 0 10px; }
  .nav-label {
    font-size: 10px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase;
    color: var(--sidebar-muted); padding: 14px 8px 6px;
  }
  .nav-item {
    display: flex; align-items: center; justify-content: space-between; gap: 8px;
    padding: 8px; border-radius: 6px; font-size: 13px; color: var(--sidebar-text);
    text-decoration: none; min-height: 34px;
  }
  .nav-item:hover { background: rgba(255,255,255,0.07); }
  .nav-item[aria-current='page'] { background: var(--accent); color: var(--accent-on); font-weight: 600; }
  .nav-count { font-size: 11px; padding: 1px 6px; border-radius: 999px; background: rgba(255,255,255,0.13); }
  .nav-item[aria-current='page'] .nav-count { background: rgba(0,0,0,0.22); }
  .nav-count.is-urgent { background: var(--crit); color: #fff; font-weight: 700; }

  .main { display: flex; flex-direction: column; min-width: 0; }

  .topbar {
    display: flex; align-items: center; gap: 14px;
    padding: 14px 20px; background: var(--surface); border-bottom: 1px solid var(--line);
  }
  .page-title { font-size: 17px; font-weight: 700; letter-spacing: -0.02em; margin: 0; }
  .site-picker {
    display: flex; align-items: center; gap: 7px; margin-left: 6px;
    padding: 6px 11px; border: 1px solid var(--line-strong); border-radius: 6px;
    background: var(--surface); font-size: 13px; color: var(--text-2); min-height: 34px; cursor: pointer;
  }
  .site-picker strong { color: var(--text-1); font-weight: 600; }
  .spacer { flex: 1 1 auto; }
  .live { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-2); }
  .live-dot {
    width: 7px; height: 7px; border-radius: 50%; background: var(--safe);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--safe) 18%, transparent);
  }
  .avatar {
    width: 30px; height: 30px; border-radius: 50%; background: var(--accent-tint);
    color: var(--accent-ink); display: grid; place-items: center;
    font-size: 12px; font-weight: 700; border: 1px solid var(--line);
  }

  .eyebrow {
    font-size: 10.5px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase;
    color: var(--text-muted); margin: 0 0 6px;
  }

  .badge {
    display: inline-flex; align-items: center; gap: 5px; padding: 2px 8px;
    border-radius: 4px; font-size: 11.5px; font-weight: 700; letter-spacing: 0.01em; white-space: nowrap;
  }
  .badge-crit { background: var(--crit-bg); color: var(--crit-ink); }
  .badge-high { background: var(--high-bg); color: var(--high-ink); }
  .badge-mid  { background: var(--mid-bg);  color: var(--mid-ink); }
  .badge-safe { background: var(--safe-bg); color: var(--safe-ink); }
  .badge .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }

  .state {
    display: inline-flex; align-items: center; gap: 5px; padding: 2px 8px;
    border-radius: 999px; font-size: 11.5px; border: 1px solid var(--line-strong);
    color: var(--text-2); background: var(--surface); white-space: nowrap;
  }
  .state-unassigned { border-color: var(--crit); color: var(--crit-ink); background: var(--crit-bg); font-weight: 600; }
  .state-review { border-color: var(--mid); color: var(--mid-ink); background: var(--mid-bg); }
  .state-confirmed { border-color: var(--safe); color: var(--safe-ink); background: var(--safe-bg); }

  .btn {
    font: inherit; font-size: 13.5px; font-weight: 600; min-height: 38px; padding: 0 16px;
    border-radius: 6px; cursor: pointer; border: 1px solid var(--line-strong);
    background: var(--surface); color: var(--text-1);
    display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  }
  .btn:hover { background: var(--sunk); }
  .btn-primary { background: var(--accent); border-color: var(--accent); color: var(--accent-on); }
  .btn-primary:hover { background: var(--accent-hover); }
  .btn-danger { color: var(--crit-ink); border-color: color-mix(in srgb, var(--crit) 40%, var(--line-strong)); }
  .btn-danger:hover { background: var(--crit-bg); }

  @media (max-width: 880px) {
    .shell { grid-template-columns: 1fr; }
    .side { display: none; }
  }
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
  }
"""

# ═══════════════════════════════════════════════════════════════════════════
# 트리아지 화면 전용 CSS
# ═══════════════════════════════════════════════════════════════════════════
TRIAGE_CSS = """
  .queue { display: flex; padding: 0 20px; background: var(--surface); border-bottom: 1px solid var(--line); }
  .q {
    flex: 1 1 0; padding: 13px 14px 14px; border-right: 1px solid var(--line);
    display: flex; flex-direction: column; gap: 3px; text-align: left;
    background: none; border-top: 0; border-bottom: 0; border-left: 0; cursor: pointer;
    font: inherit; color: inherit; position: relative;
  }
  .q:last-child { border-right: 0; }
  .q[aria-pressed='true']::after {
    content: ''; position: absolute; left: 0; right: 0; bottom: -1px; height: 2px; background: var(--accent);
  }
  .q-k { font-size: 11.5px; color: var(--text-2); font-weight: 600; }
  .q-v { font-size: 23px; font-weight: 700; letter-spacing: -0.03em; line-height: 1.1; }
  .q-note { font-size: 11px; color: var(--text-muted); }
  .q.is-crit .q-v { color: var(--crit); }
  .q.is-crit .q-note { color: var(--crit-ink); }

  .work { display: grid; grid-template-columns: minmax(0, 1fr) 396px; flex: 1 1 auto; min-height: 0; }
  .list-col { border-right: 1px solid var(--line); display: flex; flex-direction: column; min-width: 0; }

  .toolbar {
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
    padding: 11px 18px; border-bottom: 1px solid var(--line); background: var(--page);
  }
  .chip {
    padding: 5px 11px; border-radius: 999px; border: 1px solid var(--line-strong);
    background: var(--surface); font-size: 12.5px; color: var(--text-2);
    cursor: pointer; min-height: 30px; display: inline-flex; align-items: center; gap: 5px;
  }
  .chip[aria-pressed='true'] {
    background: var(--accent); border-color: var(--accent); color: var(--accent-on); font-weight: 600;
  }
  .sort { margin-left: auto; font-size: 12.5px; color: var(--text-2); display: flex; align-items: center; gap: 6px; }
  .sort select {
    font: inherit; padding: 5px 8px; border: 1px solid var(--line-strong);
    border-radius: 6px; background: var(--surface); color: var(--text-1); min-height: 30px;
  }

  .rows { list-style: none; margin: 0; padding: 0; overflow-y: auto; }
  /* 정렬 규칙이 그룹을 만들 때만 나타난다 — 규칙이 보이지 않으면 사용자는 순서를 못 믿는다. */
  .group-head {
    padding: 7px 18px; background: var(--sunk); border-bottom: 1px solid var(--line);
    font-size: 11px; font-weight: 700; letter-spacing: 0.06em; color: var(--text-2); text-transform: none;
  }
  .sort-note {
    margin: 0; padding: 9px 18px; background: var(--accent-tint);
    border-bottom: 1px solid var(--line); font-size: 12.5px; color: var(--accent-ink);
  }
  .row {
    display: grid; grid-template-columns: 4px minmax(0,1fr) auto;
    gap: 0 13px; border-bottom: 1px solid var(--line);
    background: var(--surface); cursor: pointer; position: relative;
  }
  .row:hover { background: var(--sunk); }
  /* 좌측 = 심각도, 우측 = 지금 상세에 열려 있는 행. 두 신호가 같은 변에서 싸우지 않게 나눈다. */
  .row.is-open { background: var(--accent-tint); box-shadow: inset -3px 0 0 var(--accent); }
  .sev-stripe { grid-row: 1 / -1; }
  .sev-crit .sev-stripe { background: var(--crit); }
  .sev-high .sev-stripe { background: var(--high); }
  .sev-mid  .sev-stripe { background: var(--mid); }
  .row-body { padding: 12px 0 13px; min-width: 0; }
  .row-side { padding: 12px 16px 13px 0; text-align: right; display: flex; flex-direction: column; gap: 6px; align-items: flex-end; }

  /* 행의 주인공은 '무슨 일이 일어났는가'다 — 장치 ID가 아니다 */
  .ev-what { font-size: 15px; font-weight: 700; letter-spacing: -0.015em; margin: 0 0 3px; }
  .ev-where { font-size: 12.5px; color: var(--text-2); margin: 0 0 9px; }
  .ev-where .sep { color: var(--text-muted); margin: 0 5px; }

  /* ══════════════ 시그니처: 방치 시간 막대 ══════════════
     이 제품의 진짜 실패는 '감지 못 함'이 아니라 '감지했는데 아무도 안 봄'이다.
     그래서 각 행이 SLA 대비 얼마나 방치됐는지를 한 줄로 말한다.

     막대는 '아무도 안 보고 있다'를 뜻한다 — 그래서 세 상태에서 다르게 행동한다:
       미조치  막대가 심각도 색으로 차오른다(차오를수록 나쁨)
       검토 중  담당자가 붙었으므로 긴장을 내린다 — 중립색
       처리됨  막대를 아예 그리지 않는다. 같은 장치가 '나쁨'과 '좋음'을
               동시에 뜻하면 신호가 죽는다(초록 35%가 무슨 뜻인지 아무도 모른다). */
  .dwell { display: flex; align-items: center; gap: 9px; }
  .dwell-track {
    flex: 1 1 auto; height: 3px; border-radius: 999px; background: var(--sunk);
    overflow: hidden; min-width: 60px;
  }
  .dwell-fill { display: block; height: 100%; border-radius: 999px; background: var(--text-muted); }
  .dwell-text { font-size: 11.5px; font-weight: 600; white-space: nowrap; letter-spacing: -0.01em; }
  .dwell-sla { font-size: 10.5px; color: var(--text-muted); white-space: nowrap; }
  .sev-crit .dwell-open .dwell-fill { background: var(--crit); }
  .sev-crit .dwell-open .dwell-text { color: var(--crit); }
  .sev-high .dwell-open .dwell-fill { background: var(--high); }
  .sev-high .dwell-open .dwell-text { color: var(--high-ink); }
  .sev-mid  .dwell-open .dwell-fill { background: var(--mid); }
  .sev-mid  .dwell-open .dwell-text { color: var(--mid-ink); }
  .dwell-review .dwell-text { color: var(--text-2); font-weight: 600; }
  .dwell-done .dwell-text { color: var(--safe-ink); }

  /* 정렬 비교용 — 막대를 뺀 '경과 시간 텍스트만' 변형 */
  .dwell-plain .dwell-track { display: none; }
  .dwell-plain .dwell-text { color: var(--text-2); font-weight: 500; }

  .conf { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--text-muted); }
  .conf-track { width: 42px; height: 3px; border-radius: 999px; background: var(--sunk); overflow: hidden; }
  .conf-fill { display: block; height: 100%; background: var(--text-muted); border-radius: 999px; }

  .detail { background: var(--surface); display: flex; flex-direction: column; min-width: 0; overflow-y: auto; }
  .detail-head { padding: 15px 18px 13px; border-bottom: 1px solid var(--line); }
  .detail-title { font-size: 17px; font-weight: 700; letter-spacing: -0.02em; margin: 0 0 8px; }
  .detail-meta { display: flex; gap: 7px; flex-wrap: wrap; }

  .frame {
    margin: 14px 18px 0; border-radius: 7px; overflow: hidden;
    background: #0D1416; aspect-ratio: 16 / 9; position: relative; border: 1px solid var(--line);
  }
  .frame-grid {
    position: absolute; inset: 0;
    background-image:
      linear-gradient(to right, rgba(255,255,255,0.045) 1px, transparent 1px),
      linear-gradient(to bottom, rgba(255,255,255,0.045) 1px, transparent 1px);
    background-size: 34px 34px;
  }
  /* 검출 박스 — 심각도 색을 그대로 쓴다(목록의 배지와 같은 의미, 같은 색) */
  .bbox {
    position: absolute; border: 2px solid var(--crit); border-radius: 2px;
    left: 27%; top: 31%; width: 20%; height: 46%; box-shadow: 0 0 0 1px rgba(0,0,0,0.5);
  }
  .bbox::after {
    content: '작업자 0.94'; position: absolute; left: -2px; top: -19px;
    background: var(--crit); color: #fff; font-size: 10px; font-weight: 700;
    padding: 1px 5px; border-radius: 2px; white-space: nowrap;
  }
  .zone {
    position: absolute; left: 15%; top: 22%; width: 48%; height: 66%;
    border: 1.5px dashed rgba(255,255,255,0.5); border-radius: 3px;
  }
  .zone::after {
    content: '통제구역 · A-N-01'; position: absolute; right: 4px; bottom: 4px;
    font-size: 9.5px; color: rgba(255,255,255,0.72); letter-spacing: 0.03em;
  }
  .frame-stamp {
    position: absolute; left: 9px; bottom: 8px; font-size: 10px;
    color: rgba(255,255,255,0.66); letter-spacing: 0.02em;
  }

  .facts { margin: 15px 18px 0; border-top: 1px solid var(--line); }
  .fact {
    display: grid; grid-template-columns: 92px 1fr; gap: 10px;
    padding: 8px 0; border-bottom: 1px solid var(--line); align-items: baseline;
  }
  .fact-k { font-size: 12px; color: var(--text-muted); }
  .fact-v { font-size: 13px; color: var(--text-1); min-width: 0; overflow-wrap: anywhere; }

  .actions { margin-top: auto; padding: 15px 18px 18px; border-top: 1px solid var(--line); background: var(--page); }
  .actions-label { font-size: 12px; color: var(--text-2); margin: 0 0 9px; }
  .btn-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .btn-row .btn-primary { grid-column: 1 / -1; }
  .actions-hint { font-size: 11.5px; color: var(--text-muted); margin: 9px 0 0; }

  /* 태블릿 가로(1024~1279): 상세를 340으로 줄여 목록 폭을 지킨다. 접지 않는다. */
  @media (max-width: 1279px) {
    .work { grid-template-columns: minmax(0, 1fr) 340px; }
    .frame, .facts, .detail-head, .actions { --pad: 15px; }
    .row-body { padding-right: 4px; }
  }
  /* 여기서부터는 한 화면에 둘을 못 넣는다 — 태블릿 세로·폰의 보조 경로. */
  @media (max-width: 1000px) {
    .work { grid-template-columns: minmax(0, 1fr); }
    .detail { border-top: 1px solid var(--line); }
    .list-col { border-right: 0; }
  }
  @media (max-width: 880px) {
    .queue { overflow-x: auto; }
    .q { min-width: 116px; }
  }
"""

# ═══════════════════════════════════════════════════════════════════════════
# 홈(현황판) 전용 CSS
# ═══════════════════════════════════════════════════════════════════════════
HOME_CSS = """
  .home { padding: 20px; display: flex; flex-direction: column; gap: 18px; }

  /* 오늘 가장 급한 것 하나 — 현황판이 답해야 할 질문은 '지금 뭘 해야 하나'다.
     KPI 타일 넉 장을 먼저 보여주는 건 그 질문에 답하지 않는다. */
  .callout {
    display: flex; align-items: center; gap: 16px; padding: 16px 18px;
    background: var(--surface); border: 1px solid var(--line);
    border-left: 4px solid var(--crit); border-radius: 8px;
  }
  .callout-icon {
    width: 40px; height: 40px; flex: none; border-radius: 8px;
    background: var(--crit-bg); color: var(--crit); display: grid; place-items: center;
    font-size: 19px; font-weight: 800;
  }
  .callout-body { flex: 1 1 auto; min-width: 0; }
  .callout-title { font-size: 15.5px; font-weight: 700; margin: 0 0 3px; letter-spacing: -0.015em; }
  .callout-sub { font-size: 13px; color: var(--text-2); margin: 0; }

  .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
  .stat {
    background: var(--surface); border: 1px solid var(--line); border-radius: 8px;
    padding: 13px 15px 14px; display: flex; flex-direction: column; gap: 2px;
  }
  .stat-k { font-size: 12px; color: var(--text-2); font-weight: 600; }
  .stat-v { font-size: 26px; font-weight: 700; letter-spacing: -0.035em; line-height: 1.15; }
  .stat-n { font-size: 11.5px; color: var(--text-muted); }
  .stat-n.is-good { color: var(--safe-ink); }

  .section-head { display: flex; align-items: baseline; gap: 10px; margin: 4px 0 0; }
  .section-title { font-size: 15px; font-weight: 700; margin: 0; letter-spacing: -0.015em; }
  .section-note { font-size: 12.5px; color: var(--text-muted); }
  /* 흰 배경 위 텍스트에는 --accent-text 를 쓴다. 밝은 액센트(카키 등)는 배경으로는
     읽히지만 텍스트로는 대비가 안 나오므로, 그런 방향만 이 토큰을 어둡게 재정의한다. */
  .section-link { margin-left: auto; font-size: 12.5px; color: var(--accent-text, var(--accent)); text-decoration: none; font-weight: 600; }

  .sites { display: grid; grid-template-columns: repeat(auto-fit, minmax(238px, 1fr)); gap: 12px; }
  .site-card {
    background: var(--surface); border: 1px solid var(--line); border-radius: 8px;
    padding: 15px 16px 14px; display: flex; flex-direction: column; gap: 10px;
    text-decoration: none; color: inherit;
  }
  .site-card:hover { border-color: var(--line-strong); }
  .site-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
  .site-name { font-size: 14.5px; font-weight: 700; margin: 0; letter-spacing: -0.015em; }
  .site-addr { font-size: 12px; color: var(--text-muted); margin: 2px 0 0; }
  /* 카드 높이는 그리드가 맞추되 사실 줄은 항상 바닥에 붙는다 — 설명이 있는 카드와
     없는 카드가 섞여도 눈이 훑는 가로줄이 어긋나지 않게. */
  .site-facts { display: flex; gap: 14px; padding-top: 10px; margin-top: auto; border-top: 1px solid var(--line); }
  .site-fact { display: flex; flex-direction: column; gap: 1px; }
  .site-fact-k { font-size: 10.5px; color: var(--text-muted); }
  .site-fact-v { font-size: 13px; font-weight: 600; }

  /* 미매핑 현장 — 순찰이 아예 불가능한 상태. 빈 카드가 아니라 '할 일'로 보여준다. */
  .site-card.is-todo { border-style: dashed; border-color: var(--line-strong); background: var(--sunk); }
  .site-todo-msg { font-size: 12.5px; color: var(--text-2); margin: 0; }

  .timeline { background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 15px 16px 6px; }
  .tl-row { display: grid; grid-template-columns: 62px 1fr auto; gap: 12px; align-items: center; padding: 9px 0; border-bottom: 1px solid var(--line); }
  .tl-row:last-child { border-bottom: 0; }
  .tl-time { font-size: 12px; color: var(--text-muted); }
  .tl-what { font-size: 13.5px; min-width: 0; }
  .tl-what b { font-weight: 600; }

  /* 1024 태블릿 가로에서는 통계 4열·현장 3열이 그대로 들어간다(main 폭 848).
     2열로 접는 건 그보다 좁아졌을 때다. */
  @media (max-width: 900px) {
    .stats { grid-template-columns: repeat(2, 1fr); }
  }
"""

# ═══════════════════════════════════════════════════════════════════════════
# Wizard 전용 CSS — 액센트가 가장 많이 노출되는 화면(스텝퍼·포커스·기본 버튼)
# ═══════════════════════════════════════════════════════════════════════════
WIZARD_CSS = """
  .wiz { padding: 22px 20px 28px; max-width: 940px; width: 100%; margin: 0 auto;
         display: flex; flex-direction: column; gap: 20px; }

  /* 스텝퍼는 '몇 단계 남았나'를 말한다 — 번호가 실제 순서를 뜻하므로 번호를 쓴다. */
  .stepper { display: flex; align-items: center; gap: 0; }
  .step { display: flex; align-items: center; gap: 9px; flex: 0 0 auto; }
  .step-dot {
    width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center;
    font-size: 12px; font-weight: 700; border: 1.5px solid var(--line-strong);
    background: var(--surface); color: var(--text-muted);
  }
  .step-label { font-size: 13px; color: var(--text-muted); font-weight: 600; }
  .step.is-done .step-dot { background: var(--accent); border-color: var(--accent); color: var(--accent-on); }
  .step.is-done .step-label { color: var(--text-2); }
  .step.is-now .step-dot {
    border-color: var(--accent); color: var(--accent-ink); background: var(--accent-tint);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 14%, transparent);
  }
  .step.is-now .step-label { color: var(--text-1); }
  .step-line { flex: 1 1 auto; height: 1.5px; background: var(--line-strong); margin: 0 12px; min-width: 20px; }
  .step-line.is-done { background: var(--accent); }

  .wiz-card { background: var(--surface); border: 1px solid var(--line); border-radius: 9px; overflow: hidden; }
  .wiz-head { padding: 17px 20px 15px; border-bottom: 1px solid var(--line); }
  .wiz-title { font-size: 18px; font-weight: 700; margin: 0 0 4px; letter-spacing: -0.02em; }
  .wiz-help { font-size: 13px; color: var(--text-2); margin: 0; }
  .wiz-body { padding: 18px 20px 20px; display: grid; grid-template-columns: 1fr 1fr; gap: 15px 16px; }

  .field { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .field-wide { grid-column: 1 / -1; }
  .label { font-size: 12.5px; font-weight: 600; color: var(--text-1); }
  .label .req { color: var(--crit); margin-left: 2px; }
  .input {
    font: inherit; font-size: 13.5px; min-height: 38px; padding: 0 11px;
    border: 1px solid var(--line-strong); border-radius: 6px;
    background: var(--surface); color: var(--text-1); width: 100%;
  }
  .input::placeholder { color: var(--text-muted); }
  /* 지금 입력 중인 칸 — 액센트 링. 화면에서 액센트가 가장 자주 나타나는 자리다. */
  .input.is-focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 16%, transparent);
  }
  .hint { font-size: 11.5px; color: var(--text-muted); }
  /* 에러는 사과하지 않고, 무엇이 잘못됐고 어떻게 고치는지 말한다. */
  .input.is-error { border-color: var(--crit); }
  .err { font-size: 11.5px; color: var(--crit-ink); font-weight: 600; }

  .pair { display: grid; grid-template-columns: 1fr auto 1fr; gap: 8px; align-items: center; }
  .pair-sep { color: var(--text-muted); font-size: 13px; }

  .wiz-foot {
    display: flex; align-items: center; gap: 10px;
    padding: 14px 20px; border-top: 1px solid var(--line); background: var(--page);
  }
  .wiz-foot .btn-primary { margin-left: auto; }
  .foot-note { font-size: 12px; color: var(--text-muted); }

  @media (max-width: 760px) {
    .wiz-body { grid-template-columns: 1fr; }
    .step-label { display: none; }
    .step-line { margin: 0 6px; }
  }
"""


# ═══════════════════════════════════════════════════════════════════════════
# 데이터 + 부분 렌더러
# ═══════════════════════════════════════════════════════════════════════════
def dwell(pct: int, text: str, sla: str, state: str = "open") -> str:
    """방치 시간 한 줄. state: open(미조치) | review(검토 중) | done(처리됨) | plain(막대 없음)."""
    track = (
        f'<span class="dwell-track"><span class="dwell-fill" style="width: {pct}%"></span></span>'
        if state not in ("done", "plain")
        else '<span class="dwell-track" aria-hidden="true" style="visibility:hidden"></span>'
    )
    return f"""<div class="dwell dwell-{state}">
              <span class="dwell-text num">{text}</span>
              {track}
              <span class="dwell-sla">{sla}</span>
            </div>"""


def sidebar(active: str) -> str:
    items = [
        ("오늘", [("홈", "home", ""), ("이벤트 트리아지", "triage", '<span class="nav-count is-urgent num">4</span>'),
                 ("진행 중 임무", "missions", '<span class="nav-count num">3</span>')]),
        ("현장", [("현장 목록", "sites", '<span class="nav-count num">3</span>'),
                 ("조사·매핑", "survey", ""), ("구역 설정", "zones", "")]),
        ("기록", [("이벤트 이력", "history", ""), ("보고서", "reports", "")]),
    ]
    groups = []
    for label, links in items:
        rows = "\n      ".join(
            f'<a class="nav-item" href="#"'
            f'{" aria-current=\"page\"" if key == active else ""}>{name}{count}</a>'
            for name, key, count in links
        )
        groups.append(f'      <div class="nav-label">{label}</div>\n      {rows}')
    body = "\n".join(groups)
    return f"""  <nav class="side" aria-label="주 메뉴">
    <div class="brand">
      <div class="brand-mark" aria-hidden="true">KSI</div>
      <div>
        <div class="brand-name">현장 지능</div>
        <div class="brand-sub num">SITE INTELLIGENCE</div>
      </div>
    </div>
    <div class="nav-group">
{body}
    </div>
  </nav>"""


# ── 트리아지 행 데이터 ──────────────────────────────────────────────────────
# 정렬 비교가 성립하려면 '심각도 순'과 '방치 시간 순'이 서로 다른 답을 내는 사례가
# 데이터 안에 있어야 한다. 그래서 두 극단을 일부러 넣었다:
#   crit-fall  가장 위험한데 방금 들어옴  → 심각도 순 상위 / 방치 순 최하위
#   mid-fence  가장 안 위험한데 사흘째    → 방치 순 1위   / 심각도 순 최하위
# 이게 없으면 세 정렬이 같은 순서로 나와 비교가 아니라 같은 그림 세 장이 된다(실제로 그랬다).
EVENTS = [
    {
        "id": "crit-gate",
        "sev": "crit", "sev_label": "위험",
        "what": "통제구역 무단진입",
        "where": "김해 3공구<span class='sep'>·</span>A블록 북측 게이트",
        "state": '<span class="state state-unassigned">담당자 없음</span>',
        "dwell_pct": 100, "dwell_text": "2시간 14분째 미조치", "dwell_sla": "목표 15분", "dwell_state": "open",
        "ago": "2시간 14분 전", "conf": (94, "0.94"),
    },
    {
        "id": "crit-fall",
        "sev": "crit", "sev_label": "위험",
        "what": "개구부 덮개 이탈 — 추락 위험",
        "where": "김해 3공구<span class='sep'>·</span>5층 엘리베이터 홀",
        "state": '<span class="state state-unassigned">담당자 없음</span>',
        "dwell_pct": 27, "dwell_text": "4분째 미조치", "dwell_sla": "목표 15분", "dwell_state": "open",
        "ago": "4분 전", "conf": (89, "0.89"),
    },
    {
        "id": "high-rail",
        "sev": "high", "sev_label": "높음",
        "what": "안전난간 미설치 구간에 작업자 접근",
        "where": "김해 3공구<span class='sep'>·</span>3층 슬래브 동측",
        "state": '<span class="state state-unassigned">담당자 없음</span>',
        "dwell_pct": 78, "dwell_text": "47분째 미조치", "dwell_sla": "목표 60분", "dwell_state": "open",
        "ago": "47분 전", "conf": (81, "0.81"),
    },
    {
        "id": "high-heavy",
        "sev": "high", "sev_label": "높음",
        "what": "중장비 선회 반경 안에 작업자",
        "where": "양산 물류센터<span class='sep'>·</span>야적장 2구역",
        "state": '<span class="state state-review">박현수 검토 중</span>',
        "dwell_pct": 22, "dwell_text": "13분째 검토 중", "dwell_sla": "목표 60분", "dwell_state": "review",
        "ago": "13분 전", "conf": (76, "0.76"),
    },
    {
        "id": "mid-fence",
        "sev": "mid", "sev_label": "보통",
        "what": "안전펜스 파손 구간",
        "where": "양산 물류센터<span class='sep'>·</span>서측 경계 12번 구간",
        "state": '<span class="state state-unassigned">담당자 없음</span>',
        "dwell_pct": 100, "dwell_text": "3일째 미조치", "dwell_sla": "목표 24시간", "dwell_state": "open",
        "ago": "3일 전", "conf": (72, "0.72"),
    },
    {
        "id": "mid-helmet",
        "sev": "mid", "sev_label": "보통",
        "what": "안전모 미착용",
        "where": "부산신항 A블록<span class='sep'>·</span>자재 반입구",
        "state": '<span class="state state-confirmed">조치 배정됨</span>',
        "dwell_pct": 0, "dwell_text": "6분 만에 조치 배정", "dwell_sla": "목표 4시간 안에", "dwell_state": "done",
        "ago": "6분 전", "conf": (68, "0.68"),
    },
]

# ── 정렬 모드 ──────────────────────────────────────────────────────────────
# 처리된 건(mid-helmet)은 어느 정렬에서도 맨 아래다 — 이미 끝난 일이 대기열 위로
# 올라오면 목록이 '할 일'이 아니라 '기록'이 된다.
SORT_MODES = {
    "dwell": {
        "label": "방치 시간 순",
        "groups": [(None, ["mid-fence", "crit-gate", "high-rail", "high-heavy", "crit-fall", "mid-helmet"])],
        "mode": "signature",
        "note": "오래 방치된 건이 맨 위. 방금 들어온 추락 위험이 다섯 번째에 있습니다.",
    },
    "severity": {
        "label": "심각도 순",
        "groups": [(None, ["crit-gate", "crit-fall", "high-rail", "high-heavy", "mid-fence", "mid-helmet"])],
        "mode": "signature",
        "note": "위험 → 높음 → 보통. 사흘째 방치된 펜스 파손이 다섯 번째로 내려갑니다.",
    },
    "hybrid": {
        "label": "위험 고정 + 방치 순",
        "groups": [
            ("위험 등급 · 항상 최상단", ["crit-gate", "crit-fall"]),
            ("그 외 · 방치 시간 순", ["mid-fence", "high-rail", "high-heavy", "mid-helmet"]),
        ],
        "mode": "signature",
        "note": "위험 2건을 위로 고정하고 그 아래를 방치 시간 순으로. 규칙이 하나 늘어난 대신 둘 다 잡습니다.",
    },
    "recent": {
        "label": "최신 순 (현행)",
        "groups": [(None, ["crit-fall", "high-heavy", "high-rail", "crit-gate", "mid-fence", "mid-helmet"])],
        "mode": "plain",
        "note": "방금 들어온 것이 맨 위. 사흘째 방치된 건이 맨 아래이고 방치 표시 자체가 없습니다.",
    },
}


def event_row(e: dict, *, is_open: bool = False, dwell_mode: str = "signature") -> str:
    """이벤트 목록 한 행.

    dwell_mode: signature(방치 막대) | plain(경과 시간 텍스트만 — 정렬 비교의 대조군)
    """
    conf_pct, conf_txt = e["conf"]
    if dwell_mode == "plain":
        line = dwell(0, e["ago"], "", state="plain")
    else:
        line = dwell(e["dwell_pct"], e["dwell_text"], e["dwell_sla"], state=e["dwell_state"])
    open_cls = " is-open" if is_open else ""
    return f"""        <li class="row sev-{e['sev']}{open_cls}" tabindex="0">
          <span class="sev-stripe" aria-hidden="true"></span>
          <div class="row-body">
            <h3 class="ev-what">{e['what']}</h3>
            <p class="ev-where">{e['where']}</p>
            {line}
          </div>
          <div class="row-side">
            <span class="badge badge-{e['sev']}"><span class="dot" aria-hidden="true"></span>{e['sev_label']}</span>
            {e['state']}
            <span class="conf">신뢰도
              <span class="conf-track"><span class="conf-fill" style="width: {conf_pct}%"></span></span>
              <span class="num">{conf_txt}</span>
            </span>
          </div>
        </li>"""


# ═══════════════════════════════════════════════════════════════════════════
# 화면 본문
# ═══════════════════════════════════════════════════════════════════════════
def body_triage(sort_key: str = "dwell", *, show_note: bool = False) -> str:
    by_id = {e["id"]: e for e in EVENTS}
    cfg = SORT_MODES[sort_key]
    # 정렬 비교용 주석 줄. 실제 제품 화면에는 없다 — 검토 자료에서만 켠다.
    note = f'        <p class="sort-note">{cfg["note"]}</p>' if show_note else ""
    parts = []
    for heading, ids in cfg["groups"]:
        if heading:
            parts.append(f'        <li class="group-head">{heading}</li>')
        parts.extend(
            # 상세에 열려 있는 건 운영자가 방금 클릭한 행 — 맨 위 행일 필요는 없다.
            event_row(by_id[i], is_open=(i == "crit-gate"), dwell_mode=cfg["mode"])
            for i in ids
        )
    rows = "\n".join(parts)
    options = "".join(
        f'<option{" selected" if k == sort_key else ""}>{v["label"]}</option>'
        for k, v in SORT_MODES.items()
    )
    return f"""<div class="shell">
{sidebar('triage')}
  <div class="main">
    <header class="topbar">
      <h1 class="page-title">이벤트 트리아지</h1>
      <button class="site-picker" type="button"><strong>전체 현장</strong> 3곳 <span aria-hidden="true">▾</span></button>
      <span class="spacer"></span>
      <span class="live"><span class="live-dot" aria-hidden="true"></span>순찰 2대 비행 중</span>
      <div class="avatar" title="송재철">송</div>
    </header>

    <div class="queue" role="group" aria-label="대기열 필터">
      <button class="q is-crit" type="button" aria-pressed="true">
        <span class="q-k">담당자 없음</span><span class="q-v num">4</span>
        <span class="q-note">가장 오래된 건 3일째</span>
      </button>
      <button class="q" type="button" aria-pressed="false">
        <span class="q-k">검토 중</span><span class="q-v num">1</span><span class="q-note">박현수</span>
      </button>
      <button class="q" type="button" aria-pressed="false">
        <span class="q-k">조치 배정됨</span><span class="q-v num">1</span><span class="q-note">오늘 종결 7건</span>
      </button>
      <button class="q" type="button" aria-pressed="false">
        <span class="q-k">오탐으로 종결</span><span class="q-v num">4</span><span class="q-note">오늘 오탐률 27%</span>
      </button>
    </div>

    <div class="work">
      <section class="list-col" aria-label="이벤트 목록">
        <div class="toolbar">
          <button class="chip" type="button" aria-pressed="true">열린 이벤트 5</button>
          <button class="chip" type="button" aria-pressed="false">내가 담당</button>
          <button class="chip" type="button" aria-pressed="false">위험만</button>
          <label class="sort">정렬
            <select>{options}</select>
          </label>
        </div>
{note}
        <ul class="rows">
{rows}
        </ul>
      </section>

      <aside class="detail" aria-label="선택한 이벤트">
        <div class="detail-head">
          <p class="eyebrow num">EVT-2026-0803-0147</p>
          <h2 class="detail-title">통제구역 무단진입</h2>
          <div class="detail-meta">
            <span class="badge badge-crit"><span class="dot" aria-hidden="true"></span>위험</span>
            <span class="state state-unassigned">담당자 없음</span>
            <span class="state">신뢰도 <span class="num">0.94</span></span>
          </div>
        </div>

        <figure class="frame">
          <div class="frame-grid" aria-hidden="true"></div>
          <div class="zone" aria-hidden="true"></div>
          <div class="bbox" aria-hidden="true"></div>
          <figcaption class="frame-stamp num">14:22:07 KST · 고도 42.3 m · 광각</figcaption>
        </figure>

        <dl class="facts">
          <div class="fact"><dt class="fact-k">현장</dt><dd class="fact-v">김해 산업단지 3공구 신축공사</dd></div>
          <div class="fact"><dt class="fact-k">위치</dt><dd class="fact-v">A블록 북측 게이트<br><span class="num">35.2284° N, 128.8894° E</span></dd></div>
          <div class="fact"><dt class="fact-k">감지 시각</dt><dd class="fact-v num">2026-08-03 14:22:07 KST</dd></div>
          <div class="fact"><dt class="fact-k">순찰 임무</dt><dd class="fact-v">정기 순찰 3회차 · <span class="num">MSN-0803-03</span></dd></div>
          <div class="fact"><dt class="fact-k">기체</dt><dd class="fact-v num">M4D-01</dd></div>
        </dl>

        <div class="actions">
          <p class="actions-label">이 이벤트를 어떻게 처리할까요?</p>
          <div class="btn-row">
            <button class="btn btn-primary" type="button">확정하고 담당자 지정</button>
            <button class="btn" type="button">보류</button>
            <button class="btn btn-danger" type="button">오탐으로 종결</button>
          </div>
          <p class="actions-hint">확정하면 담당자에게 즉시 알림이 갑니다. 처리 내역은 되돌릴 수 있습니다.</p>
        </div>
      </aside>
    </div>
  </div>
</div>"""


def body_home() -> str:
    return f"""<div class="shell">
{sidebar('home')}
  <div class="main">
    <header class="topbar">
      <h1 class="page-title">홈</h1>
      <span class="site-picker" style="cursor:default"><strong>2026년 8월 4일</strong> 월요일</span>
      <span class="spacer"></span>
      <span class="live"><span class="live-dot" aria-hidden="true"></span>순찰 2대 비행 중</span>
      <div class="avatar" title="송재철">송</div>
    </header>

    <div class="home">
      <div class="callout">
        <div class="callout-icon" aria-hidden="true">!</div>
        <div class="callout-body">
          <p class="callout-title">사흘 동안 아무도 보지 않은 이벤트가 있습니다</p>
          <p class="callout-sub">양산 물류센터 안전펜스 파손 · 담당자가 없는 이벤트가 모두 <span class="num">4</span>건입니다</p>
        </div>
        <button class="btn btn-primary" type="button">지금 처리하기</button>
      </div>

      <div class="stats">
        <div class="stat">
          <span class="stat-k">담당자 없는 이벤트</span>
          <span class="stat-v num" style="color: var(--crit)">4</span>
          <span class="stat-n">전체 열린 이벤트 5건 중</span>
        </div>
        <div class="stat">
          <span class="stat-k">오늘 순찰</span>
          <span class="stat-v num">3<span style="font-size:15px; color:var(--text-muted)"> / 5</span></span>
          <span class="stat-n">다음 순찰 15:30 김해 3공구</span>
        </div>
        <div class="stat">
          <span class="stat-k">평균 대응 시간</span>
          <span class="stat-v num">18<span style="font-size:15px; color:var(--text-muted)">분</span></span>
          <span class="stat-n is-good">지난주보다 6분 빨라졌습니다</span>
        </div>
        <div class="stat">
          <span class="stat-k">오늘 오탐률</span>
          <span class="stat-v num">27<span style="font-size:15px; color:var(--text-muted)">%</span></span>
          <span class="stat-n">오탐 4건 / 감지 15건</span>
        </div>
      </div>

      <div class="section-head">
        <h2 class="section-title">현장</h2>
        <span class="section-note">3곳 · 1곳은 아직 순찰할 수 없습니다</span>
        <a class="section-link" href="#">전체 보기</a>
      </div>
      <div class="sites">
        <a class="site-card" href="#">
          <div class="site-top">
            <div>
              <h3 class="site-name">김해 산업단지 3공구</h3>
              <p class="site-addr">경남 김해시 주촌면</p>
            </div>
            <span class="badge badge-crit"><span class="dot" aria-hidden="true"></span>위험 2</span>
          </div>
          <div class="site-facts">
            <div class="site-fact"><span class="site-fact-k">순찰</span><span class="site-fact-v">비행 중</span></div>
            <div class="site-fact"><span class="site-fact-k">구역</span><span class="site-fact-v num">7개</span></div>
            <div class="site-fact"><span class="site-fact-k">최근 매핑</span><span class="site-fact-v num">7월 29일</span></div>
          </div>
        </a>
        <a class="site-card" href="#">
          <div class="site-top">
            <div>
              <h3 class="site-name">양산 물류센터 증축</h3>
              <p class="site-addr">경남 양산시 물금읍</p>
            </div>
            <span class="badge badge-high"><span class="dot" aria-hidden="true"></span>높음 1</span>
          </div>
          <div class="site-facts">
            <div class="site-fact"><span class="site-fact-k">순찰</span><span class="site-fact-v">비행 중</span></div>
            <div class="site-fact"><span class="site-fact-k">구역</span><span class="site-fact-v num">4개</span></div>
            <div class="site-fact"><span class="site-fact-k">최근 매핑</span><span class="site-fact-v num">8월 1일</span></div>
          </div>
        </a>
        <a class="site-card is-todo" href="#">
          <div class="site-top">
            <div>
              <h3 class="site-name">부산신항 배후단지 A블록</h3>
              <p class="site-addr">부산 강서구 성북동</p>
            </div>
            <span class="state">미매핑</span>
          </div>
          <p class="site-todo-msg">기준 지도가 없어 순찰을 시작할 수 없습니다. 조사 비행을 한 번 하면 구역을 그릴 수 있습니다.</p>
          <div class="site-facts">
            <div class="site-fact"><span class="site-fact-k">등록</span><span class="site-fact-v num">8월 2일</span></div>
            <div class="site-fact"><span class="site-fact-k">다음 할 일</span><span class="site-fact-v" style="color: var(--accent-text, var(--accent))">조사 비행 계획</span></div>
          </div>
        </a>
      </div>

      <div class="section-head">
        <h2 class="section-title">오늘 있었던 일</h2>
        <a class="section-link" href="#">이벤트 이력</a>
      </div>
      <div class="timeline">
        <div class="tl-row">
          <span class="tl-time num">14:22</span>
          <span class="tl-what"><b>통제구역 무단진입</b> 감지 — 김해 3공구</span>
          <span class="state state-unassigned">담당자 없음</span>
        </div>
        <div class="tl-row">
          <span class="tl-time num">13:48</span>
          <span class="tl-what"><b>정기 순찰 3회차</b> 완료 — 김해 3공구 · 비행 <span class="num">22분</span></span>
          <span class="badge badge-safe">정상 종료</span>
        </div>
        <div class="tl-row">
          <span class="tl-time num">13:12</span>
          <span class="tl-what"><b>안전모 미착용</b> 조치 배정 — 부산신항 A블록 · 담당 이수민</span>
          <span class="state state-confirmed">조치 배정됨</span>
        </div>
        <div class="tl-row">
          <span class="tl-time num">11:05</span>
          <span class="tl-what"><b>부산신항 배후단지 A블록</b> 현장 등록 — 송재철</span>
          <span class="state">조사 대기</span>
        </div>
      </div>
    </div>
  </div>
</div>"""


def body_wizard() -> str:
    return f"""<div class="shell">
{sidebar('sites')}
  <div class="main">
    <header class="topbar">
      <h1 class="page-title">현장 등록</h1>
      <span class="spacer"></span>
      <button class="btn" type="button">저장하고 나가기</button>
      <div class="avatar" title="송재철">송</div>
    </header>

    <div class="wiz">
      <ol class="stepper" style="list-style:none; margin:0; padding:0">
        <li class="step is-done"><span class="step-dot num">1</span><span class="step-label">현장 정보</span></li>
        <span class="step-line is-done" aria-hidden="true"></span>
        <li class="step is-now"><span class="step-dot num">2</span><span class="step-label">경계와 좌표</span></li>
        <span class="step-line" aria-hidden="true"></span>
        <li class="step"><span class="step-dot num">3</span><span class="step-label">담당자</span></li>
        <span class="step-line" aria-hidden="true"></span>
        <li class="step"><span class="step-dot num">4</span><span class="step-label">확인</span></li>
      </ol>

      <div class="wiz-card">
        <div class="wiz-head">
          <h2 class="wiz-title">현장 경계와 기준점을 정합니다</h2>
          <p class="wiz-help">여기서 정한 경계가 순찰 비행 범위가 됩니다. 나중에 조사 비행으로 정밀 지도를 만들 때 이 값이 기준점이 됩니다.</p>
        </div>

        <div class="wiz-body">
          <div class="field field-wide">
            <label class="label" for="f1">현장 이름<span class="req" aria-hidden="true">*</span></label>
            <input class="input" id="f1" value="부산신항 배후단지 A블록" />
            <span class="hint">보고서와 알림에 이 이름이 그대로 나갑니다.</span>
          </div>

          <div class="field">
            <label class="label" for="f2">기준점 위도<span class="req" aria-hidden="true">*</span></label>
            <input class="input is-focus num" id="f2" value="35.0821" />
            <span class="hint">십진수 도 단위. 예: 35.0821</span>
          </div>
          <div class="field">
            <label class="label" for="f3">기준점 경도<span class="req" aria-hidden="true">*</span></label>
            <input class="input num" id="f3" value="128.8114" />
            <span class="hint">십진수 도 단위. 예: 128.8114</span>
          </div>

          <div class="field">
            <label class="label" for="f4">순찰 반경<span class="req" aria-hidden="true">*</span></label>
            <input class="input num" id="f4" value="450" />
            <span class="hint">미터. 기준점에서부터의 거리입니다.</span>
          </div>
          <div class="field">
            <label class="label" for="f5">최대 비행 고도<span class="req" aria-hidden="true">*</span></label>
            <input class="input is-error num" id="f5" value="180" />
            <span class="err">항공안전법상 150 m를 넘을 수 없습니다. 150 이하로 낮추거나 특별 승인 번호를 입력하세요.</span>
          </div>

          <div class="field field-wide">
            <label class="label">공사 기간</label>
            <div class="pair">
              <input class="input num" value="2026-08-10" aria-label="시작일" />
              <span class="pair-sep" aria-hidden="true">~</span>
              <input class="input num" value="2027-06-30" aria-label="종료일" />
            </div>
          </div>

          <div class="field field-wide">
            <label class="label" for="f6">발주처</label>
            <input class="input" id="f6" placeholder="예: 부산항만공사" />
          </div>
        </div>

        <div class="wiz-foot">
          <button class="btn" type="button">이전</button>
          <span class="foot-note">4단계 중 2단계 · 입력 내용은 자동 저장됩니다</span>
          <button class="btn btn-primary" type="button">담당자 지정으로</button>
        </div>
      </div>
    </div>
  </div>
</div>"""


# ═══════════════════════════════════════════════════════════════════════════
# 정렬 기준 비교 — 방향은 A로 고정하고 '정렬만' 바꿔 나란히 놓는다.
# 브랜드 비교와 섞지 않는다: 한 번에 한 변수만 움직여야 판단이 선다.
# ═══════════════════════════════════════════════════════════════════════════
MATRIX_CSS = """
  .mx { padding: 24px 22px 30px; max-width: 1240px; margin: 0 auto; }
  .mx-h1 { font-size: 22px; font-weight: 700; letter-spacing: -0.025em; margin: 0 0 7px; }
  .mx-lede { font-size: 14px; color: var(--text-2); margin: 0 0 8px; max-width: 72ch; }
  .mx-legend {
    display: grid; grid-template-columns: 232px repeat(4, 1fr); gap: 0 14px;
    padding: 0 0 8px; margin-top: 18px;
  }
  .mx-legend span {
    font-size: 10.5px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
    color: var(--text-muted);
  }

  .pal {
    display: grid; grid-template-columns: 232px repeat(4, 1fr); gap: 0 14px; align-items: center;
    padding: 13px 0; border-top: 1px solid var(--line);
  }
  .pal-id { min-width: 0; }
  .pal-name { font-size: 14.5px; font-weight: 700; margin: 0 0 3px; letter-spacing: -0.015em; display: flex; align-items: center; gap: 7px; }
  .pal-sw { width: 15px; height: 15px; border-radius: 4px; flex: none; background: var(--accent); border: 1px solid rgba(0,0,0,0.12); }
  .pal-hex { font-size: 11.5px; color: var(--text-muted); }
  .pal-why { font-size: 12px; color: var(--text-2); margin: 5px 0 0; }
  .pal-tag {
    display: inline-block; margin-top: 6px; font-size: 10.5px; font-weight: 700;
    padding: 2px 7px; border-radius: 4px; background: var(--sunk); color: var(--text-2);
  }
  .pal-tag.is-rec { background: var(--accent-tint); color: var(--accent-ink); }
  .pal-tag.is-decided { background: var(--safe-bg); color: var(--safe-ink); }

  .bit { min-width: 0; }
  /* 메뉴 조각 — 액센트(활성 항목)와 빨강(미조치 개수)이 세로로 붙는 자리 */
  .mini-nav { background: var(--sidebar); border-radius: 7px; padding: 7px; display: flex; flex-direction: column; gap: 3px; }
  .mini-item {
    display: flex; align-items: center; justify-content: space-between; gap: 7px;
    padding: 6px 8px; border-radius: 5px; font-size: 12px; color: var(--sidebar-text);
  }
  .mini-item.is-on { background: var(--accent); color: var(--accent-on); font-weight: 600; }
  .mini-count { font-size: 10.5px; padding: 0 5px; border-radius: 999px; background: var(--crit); color: #fff; font-weight: 700; }

  /* 경고 배너 조각 — 빨강 신호와 액센트 CTA가 나란히 서는, 충돌이 가장 잘 보이는 자리 */
  .mini-alert {
    display: flex; align-items: center; gap: 9px; padding: 9px 10px;
    background: var(--surface); border: 1px solid var(--line);
    border-left: 3px solid var(--crit); border-radius: 7px;
  }
  .mini-alert-icon {
    width: 24px; height: 24px; flex: none; border-radius: 6px;
    background: var(--crit-bg); color: var(--crit); display: grid; place-items: center;
    font-size: 13px; font-weight: 800;
  }
  .mini-alert-txt { flex: 1 1 auto; font-size: 11.5px; color: var(--text-2); min-width: 0; }
  .mini-btn { min-height: 30px; padding: 0 10px; font-size: 12px; flex: none; }

  .bit-badges { display: flex; flex-wrap: wrap; gap: 5px; align-content: center; }

  .bit-form { display: flex; flex-direction: column; gap: 9px; }
  .bit-form .input { min-height: 32px; font-size: 12.5px; }
  .mini-steps { display: flex; align-items: center; gap: 0; }
  .mini-steps .step-dot { width: 22px; height: 22px; font-size: 11px; }
  .mini-steps .step-line { flex: 1 1 auto; height: 1.5px; margin: 0 7px; background: var(--line-strong); }
  .mini-steps .step-line.is-done { background: var(--accent); }

  .pal-divider {
    margin: 22px 0 0; padding: 9px 0 0; border-top: 2px solid var(--line-strong);
    font-size: 11px; font-weight: 700; letter-spacing: 0.08em; color: var(--text-muted);
  }

  @media (max-width: 1040px) {
    .mx-legend { display: none; }
    .pal { grid-template-columns: 1fr; gap: 12px; }
  }
"""

# 2026-08-04 대표자 확정 — 잉크 모노크롬 #1F2124.
DECIDED_SLUG = "d-ink-mono"


def tag_of(d: dict) -> tuple[str, str]:
    """방향 라벨. 확정 / 후보 / 현행 / 없음."""
    if d["slug"] == DECIDED_SLUG:
        return ("확정", "is-decided")
    if d["finalist"]:
        return ("후보", "is-rec")
    if d["slug"] == "c-ksi-orange":
        return ("현행", "")
    return ("", "")


def matrix_scoped_css() -> str:
    """방향별 토큰을 행 스코프(.pal-<slug>)로 내보낸다.

    한 페이지에서 7개 팔레트를 나란히 보여주려면 :root 하나로는 안 된다. 조각 마크업은
    전부 동일하고 감싸는 행의 변수만 달라지므로, 눈에 보이는 차이는 순수하게 색이다.
    """
    return "\n".join(
        f"  .pal-{d['slug']} {{ " + " ".join(f"--{k}: {v};" for k, v in d["tokens"].items()) + " }"
        for d in DIRECTIONS
    )


def body_matrix() -> str:
    rows = []
    ordered = [d for d in DIRECTIONS if d["finalist"]] + [d for d in DIRECTIONS if not d["finalist"]]
    split_done = False
    for d in ordered:
        if not d["finalist"] and not split_done:
            rows.append('    <p class="pal-divider">이전 검토안 — 참고용으로 남겨둡니다</p>')
            split_done = True
        label, cls = tag_of(d)
        tag = f'<span class="pal-tag {cls}">{label}</span>' if label else ""
        rows.append(f"""    <div class="pal pal-{d['slug']}">
      <div class="pal-id">
        <h2 class="pal-name"><span class="pal-sw" aria-hidden="true"></span>{d['name']}</h2>
        <span class="pal-hex num">{d['tokens']['accent']}</span>
        <p class="pal-why">{d['thesis']}</p>
        {tag}
      </div>
      <div class="bit">
        <div class="mini-nav">
          <span class="mini-item is-on">이벤트 트리아지<span class="mini-count num">4</span></span>
          <span class="mini-item">진행 중 임무</span>
        </div>
      </div>
      <div class="bit">
        <div class="mini-alert">
          <span class="mini-alert-icon" aria-hidden="true">!</span>
          <span class="mini-alert-txt">사흘째 아무도 보지 않음</span>
          <button class="btn btn-primary mini-btn" type="button">지금 처리</button>
        </div>
      </div>
      <div class="bit bit-badges">
        <span class="badge badge-crit"><span class="dot" aria-hidden="true"></span>위험</span>
        <span class="badge badge-high"><span class="dot" aria-hidden="true"></span>높음</span>
        <span class="badge badge-mid"><span class="dot" aria-hidden="true"></span>보통</span>
        <span class="state state-unassigned">담당자 없음</span>
        <span class="state state-confirmed">조치 배정됨</span>
      </div>
      <div class="bit bit-form">
        <input class="input is-focus num" value="35.0821" aria-label="기준점 위도" />
        <div class="mini-steps">
          <span class="step-dot num" style="background: var(--accent); border-color: var(--accent); color: var(--accent-on)">1</span>
          <span class="step-line is-done" aria-hidden="true"></span>
          <span class="step-dot num" style="border-color: var(--accent); background: var(--accent-tint); color: var(--accent-ink)">2</span>
          <span class="step-line" aria-hidden="true"></span>
          <span class="step-dot num">3</span>
        </div>
      </div>
    </div>""")
    joined = "\n".join(rows)
    return f"""<div class="mx">
  <p class="eyebrow">브랜드 액센트 · 후보 4안 대조</p>
  <h1 class="mx-h1">잉크와 흙 — 후보 네 가지</h1>
  <p class="mx-lede">안전 상태색(위험 빨강 · 높음 주황 · 보통 파랑 · 안전 초록)은 <b>모든 안에서 동일</b>합니다. 브랜드 색이 바뀐다고 의미색이 따라 바뀌면 운영자가 학습한 신호가 무너지기 때문입니다. 따라서 여기 보이는 차이는 전부 액센트 하나에서 나옵니다.</p>
  <p class="mx-lede">특히 <b>두 번째 칸(경고 배너)</b>을 보십시오. 빨강 경고 신호와 액센트 버튼이 나란히 서는 자리입니다.</p>
  <p class="mx-lede">카키 세 안의 차이는 <b>#C3B091을 어느 자리에 쓰느냐</b>입니다. 이 색은 밝아서(흰 배경 대비 2.1:1) 본문 링크로는 못 쓰므로, 표식에만 남기거나(H) 배경으로 쓰고 글자를 어둡게 얹거나(I) 눌러서 흰 글자를 얹습니다(J).</p>

  <div class="mx-legend" aria-hidden="true">
    <span>방향</span><span>메뉴 · 활성 항목</span><span>경고 배너 + 버튼</span><span>상태 배지</span><span>입력 · 단계</span>
  </div>
{joined}
</div>"""


SCREENS = [
    {"slug": "home", "label": "홈 (현황판)", "css": HOME_CSS, "body": body_home},
    {"slug": "triage", "label": "이벤트 트리아지", "css": TRIAGE_CSS, "body": body_triage},
    {"slug": "site-wizard", "label": "현장 등록 Wizard", "css": WIZARD_CSS, "body": body_wizard},
]

# ═══════════════════════════════════════════════════════════════════════════
# 목차 — 이 파일을 브라우저로 열면 모든 시안으로 갈 수 있다.
# 서버 없이 file:// 로 열어도 상대 링크가 그대로 동작한다.
# ═══════════════════════════════════════════════════════════════════════════
INDEX_CSS = """
  .ix { padding: 26px 22px 40px; max-width: 1120px; margin: 0 auto; }
  .ix-h1 { font-size: 24px; font-weight: 700; letter-spacing: -0.03em; margin: 0 0 8px; }
  .ix-lede { font-size: 14.5px; color: var(--text-2); margin: 0 0 6px; max-width: 70ch; }
  .ix-sec { margin-top: 30px; }
  .ix-sec-h { font-size: 16px; font-weight: 700; margin: 0 0 4px; letter-spacing: -0.02em; }
  .ix-sec-note { font-size: 13px; color: var(--text-muted); margin: 0 0 14px; }

  .ix-feature { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
  .ix-card {
    display: block; padding: 16px 17px; background: var(--surface);
    border: 1px solid var(--line); border-radius: 9px; text-decoration: none; color: inherit;
  }
  .ix-card:hover { border-color: var(--accent); }
  .ix-card-t { font-size: 15px; font-weight: 700; margin: 0 0 4px; letter-spacing: -0.015em; }
  .ix-card-d { font-size: 12.5px; color: var(--text-2); margin: 0; }
  .ix-card-go { font-size: 12.5px; color: var(--accent-text, var(--accent)); font-weight: 600; margin: 9px 0 0; }

  .ix-grid { background: var(--surface); border: 1px solid var(--line); border-radius: 9px; overflow: hidden; }
  .ix-row {
    display: grid; grid-template-columns: 210px repeat(3, 1fr);
    border-bottom: 1px solid var(--line); align-items: stretch;
  }
  .ix-row:last-child { border-bottom: 0; }
  .ix-row-head {
    padding: 12px 14px; display: flex; flex-direction: column; gap: 3px; justify-content: center;
    background: var(--page); border-right: 1px solid var(--line); min-width: 0;
  }
  .ix-hdr { background: var(--sunk); }
  .ix-hdr .ix-row-head, .ix-hdr .ix-cell {
    font-size: 10.5px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
    color: var(--text-muted); padding: 9px 14px; background: var(--sunk);
  }
  .ix-hdr .ix-cell { border-left: 1px solid var(--line); }
  .ix-name { font-size: 13.5px; font-weight: 700; display: flex; align-items: center; gap: 7px; letter-spacing: -0.015em; }
  .ix-sw { width: 13px; height: 13px; border-radius: 4px; flex: none; border: 1px solid rgba(0,0,0,0.14); }
  .ix-hex { font-size: 11px; color: var(--text-muted); }
  .ix-cell {
    display: flex; align-items: center; padding: 12px 14px; border-left: 1px solid var(--line);
    font-size: 13px; color: var(--accent-text, var(--accent)); text-decoration: none; font-weight: 600; min-height: 46px;
  }
  .ix-cell:hover { background: var(--accent-tint); }
  .ix-tag {
    font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 4px;
    background: var(--accent-tint); color: var(--accent-ink); margin-left: 6px;
  }
  .ix-tag.is-decided { background: var(--safe-bg); color: var(--safe-ink); }

  /* 확정 사실을 목차 맨 위에 못 박는다 — 시안이 10개라 뭘 골랐는지가 안 보이면
     이 페이지는 "아직 고르는 중"으로 읽힌다. */
  .ix-decided {
    display: flex; align-items: flex-start; gap: 13px; margin: 0 0 22px;
    padding: 15px 17px; background: var(--surface);
    border: 1px solid var(--line); border-left: 4px solid var(--safe); border-radius: 9px;
  }
  .ix-decided-sw {
    width: 38px; height: 38px; flex: none; border-radius: 8px;
    background: #1F2124; border: 1px solid rgba(0,0,0,0.15);
  }
  .ix-decided-t { font-size: 15px; font-weight: 700; margin: 0 0 3px; letter-spacing: -0.015em; }
  .ix-decided-d { font-size: 12.5px; color: var(--text-2); margin: 0; }

  .ix-live { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
  .ix-live-card {
    display: block; padding: 15px 16px; border-radius: 9px; text-decoration: none;
    background: var(--surface); border: 1px solid var(--line);
  }
  .ix-live-card:hover { border-color: var(--accent); }
  .ix-live-t { font-size: 14.5px; font-weight: 700; margin: 0 0 4px; letter-spacing: -0.015em; }
  .ix-live-d { font-size: 12.5px; color: var(--text-2); margin: 0; }
  .ix-live-u {
    font-size: 12px; color: var(--accent-text, var(--accent)); font-weight: 600;
    margin: 8px 0 0; overflow-wrap: anywhere;
  }
  .ix-key {
    display: inline-block; margin-top: 7px; padding: 3px 8px; border-radius: 5px;
    background: var(--sunk); font-size: 12px;
  }
  @media (max-width: 700px) { .ix-live { grid-template-columns: 1fr; } }
  .ix-note { font-size: 12.5px; color: var(--text-2); margin: 14px 0 0; padding-left: 12px; border-left: 2px solid var(--line-strong); }

  .ix-split {
    padding: 9px 14px; background: var(--sunk); border-bottom: 1px solid var(--line);
    font-size: 10.5px; font-weight: 700; letter-spacing: 0.08em; color: var(--text-muted);
  }

  @media (max-width: 820px) {
    .ix-feature { grid-template-columns: 1fr; }
    .ix-row { grid-template-columns: 1fr; }
    .ix-hdr { display: none; }
    .ix-row-head { border-right: 0; border-bottom: 1px solid var(--line); }
    .ix-cell { border-left: 0; }
  }
"""


def body_index() -> str:
    sort_cards = "\n".join(
        f"""    <a class="ix-card" href="studies/sort-{k}.html">
      <p class="ix-card-t">{v['label']}</p>
      <p class="ix-card-d">{v['note']}</p>
      <p class="ix-card-go">화면으로 보기 →</p>
    </a>"""
        for k, v in SORT_MODES.items()
    )
    rows = []
    ordered = [d for d in DIRECTIONS if d["finalist"]] + [d for d in DIRECTIONS if not d["finalist"]]
    split_done = False
    for d in ordered:
        if not d["finalist"] and not split_done:
            rows.append('    <div class="ix-split">이전 검토안 — 참고용</div>')
            split_done = True
        label, _ = tag_of(d)
        tag_cls = " is-decided" if d["slug"] == DECIDED_SLUG else ""
        tag = f'<span class="ix-tag{tag_cls}">{label}</span>' if label else ""
        cells = "\n".join(
            f'      <a class="ix-cell" href="screens/{s["slug"]}-{d["slug"]}.html">{s["label"]} 열기</a>'
            for s in SCREENS
        )
        rows.append(f"""    <div class="ix-row">
      <div class="ix-row-head">
        <span class="ix-name"><span class="ix-sw" style="background: {d['tokens']['accent']}"></span>{d['name']}{tag}</span>
        <span class="ix-hex num">{d['tokens']['accent']}</span>
      </div>
{cells}
    </div>""")
    joined = "\n".join(rows)
    return f"""<div class="ix">
  <p class="eyebrow">KSI 현장 지능 · 디자인</p>
  <h1 class="ix-h1">확정된 것과 아직 정할 것</h1>

  <div class="ix-decided">
    <span class="ix-decided-sw" aria-hidden="true"></span>
    <div>
      <p class="ix-decided-t">브랜드 액센트 확정 — 잉크 모노크롬 <span class="num">#1F2124</span></p>
      <p class="ix-decided-d">브랜드에 색을 쓰지 않습니다. 화면에서 색이 있는 곳은 안전 상태(위험·높음·보통·안전)뿐이고, 그래서 경고가 다른 무엇과도 경쟁하지 않습니다. 실제 대시보드에 이미 반영돼 있습니다.</p>
    </div>
  </div>

  <div class="ix-sec" style="margin-top: 0">
    <h2 class="ix-sec-h">실제로 동작하는 화면</h2>
    <p class="ix-sec-note">아래 시안이 아니라 진짜 제품입니다. 개발 서버가 떠 있을 때만 열립니다.</p>
    <div class="ix-live">
      <a class="ix-live-card" href="http://localhost:3000/events">
        <p class="ix-live-t">이벤트 트리아지 (실제)</p>
        <p class="ix-live-d">확정색 · 방치 시간 · 확인 SLA 가 적용된 화면입니다.</p>
        <p class="ix-live-u num">http://localhost:3000/events</p>
        <span class="ix-key num">로그인 토큰: dev-admin-token</span>
      </a>
      <a class="ix-live-card" href="http://localhost:3000/">
        <p class="ix-live-t">홈 · 현장 · 임무 (실제)</p>
        <p class="ix-live-d">대시보드 전체. 좌측 메뉴로 이동합니다.</p>
        <p class="ix-live-u num">http://localhost:3000</p>
        <span class="ix-key num">로그인 토큰: dev-admin-token</span>
      </a>
    </div>
  </div>
  <p class="ix-lede">브랜드 액센트와 목록 정렬(위험 고정 + 방치 순)은 정해졌고 실제 코드에 들어갔습니다. 아래 시안들은 <b>그 결정의 근거와 대안</b>으로 남겨둡니다.</p>
  <p class="ix-lede">화면은 <b>태블릿 가로(1024)와 데스크톱</b>을 1급으로 잡았습니다. 태블릿 가로에서도 목록과 상세가 한 화면에 남습니다 — 브라우저 창을 좁혀 보시면 확인됩니다.</p>

  <div class="ix-sec">
    <h2 class="ix-sec-h">브랜드 후보 대조 (결정 근거)</h2>
    <p class="ix-sec-note">같은 UI 조각을 액센트만 바꿔 나란히 놓은 한 장입니다. 위쪽 네 줄이 후보(잉크 계열 1 · 카키 계열 3)이고, 구분선 아래는 이전 검토안입니다.</p>
    <div class="ix-feature">
      <a class="ix-card" href="studies/palette-matrix.html" style="grid-column: 1 / -1">
        <p class="ix-card-t">브랜드 액센트 대조표 — 잉크 1안 + 카키 3안</p>
        <p class="ix-card-d">메뉴 · 경고 배너 + 버튼 · 상태 배지 · 입력/단계. 안전 상태색은 모든 안에서 동일하므로 보이는 차이는 전부 액센트 하나에서 나옵니다.</p>
        <p class="ix-card-go">대조표 열기 →</p>
      </a>
    </div>
  </div>

  <div class="ix-sec">
    <h2 class="ix-sec-h">방향별 전체 화면</h2>
    <p class="ix-sec-note">가로 = 화면 종류, 세로 = 브랜드 방향. 아무 칸이나 누르면 그 조합의 전체 화면이 열립니다.</p>
    <div class="ix-grid">
      <div class="ix-row ix-hdr">
        <div class="ix-row-head">방향</div>
        <span class="ix-cell">홈</span><span class="ix-cell">트리아지</span><span class="ix-cell">현장 등록</span>
      </div>
{joined}
    </div>
    <p class="ix-note">Wizard 화면이 액센트를 가장 많이 씁니다(단계 표시 · 입력 포커스 · 기본 버튼). 색을 판단하실 때 이 화면을 꼭 한 번 보십시오.</p>
  </div>

  <div class="ix-sec">
    <h2 class="ix-sec-h">정렬 비교 (결정 근거)</h2>
    <p class="ix-sec-note">색은 계측 청록으로 고정하고 정렬만 바꿨습니다. 같은 이벤트 6건이 어떤 순서로 놓이는지 보십시오.</p>
    <div class="ix-feature">
{sort_cards}
    </div>
    <p class="ix-note">여기서 정하는 것은 <b>아무도 손대지 않았을 때의 기본값</b>입니다. 운영자가 화면에서 정렬을 바꾸는 것은 네 안 모두 가능합니다.</p>
  </div>
</div>"""


def page(*, title: str, group: str, tokens: dict, css: str, body: str, note: str) -> str:
    token_lines = "\n".join(f"    --{k}: {v};" for k, v in tokens.items())
    return f"""<!-- @dsCard group="{group}" -->
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{title}</title>
<style>
  /* {note} */
  :root {{
{token_lines}
    --radius: 7px;
  }}
{BASE_CSS}
{css}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def build() -> None:
    (OUT / "screens").mkdir(parents=True, exist_ok=True)
    (OUT / "studies").mkdir(parents=True, exist_ok=True)
    made = []

    for d in DIRECTIONS:
        tokens = {**d["tokens"], **SAFETY}
        for s in SCREENS:
            html = page(
                title=f"{s['label']} — {d['name']}",
                group=s["label"],
                tokens=tokens,
                css=s["css"],
                body=s["body"](),
                note=(
                    f"방향 {d['slug'][0].upper()} — {d['name']} ({d['en']})\n"
                    f"     {d['thesis']}\n"
                    "     안전 상태색(위험/높음/보통/안전)은 전 방향 공통 — 브랜드가 바뀌어도 의미색은 안 바뀐다."
                ),
            )
            p = OUT / "screens" / f"{s['slug']}-{d['slug']}.html"
            p.write_text(html, encoding="utf-8")
            made.append(p)

    a = DIRECTIONS[0]
    a_tokens = {**a["tokens"], **SAFETY}

    # 브랜드 대조표 — 7안을 한 페이지에서 행 스코프 변수로 나란히
    p = OUT / "studies" / "palette-matrix.html"
    p.write_text(
        page(
            title="브랜드 액센트 7안 대조",
            group="검토 자료",
            tokens=a_tokens,
            css=WIZARD_CSS + MATRIX_CSS + "\n" + matrix_scoped_css(),
            body=body_matrix(),
            note="브랜드 액센트 대조 — 조각 마크업은 전부 동일하고 감싸는 행의 변수만 다르다.",
        ),
        encoding="utf-8",
    )
    made.append(p)

    # 정렬 비교는 실제 트리아지 화면으로. 팔레트는 방향 A 고정 — 한 번에 한 변수만 움직인다.
    for key, cfg in SORT_MODES.items():
        p = OUT / "studies" / f"sort-{key}.html"
        p.write_text(
            page(
                title=f"기본 정렬 — {cfg['label']}",
                group="검토 자료 · 정렬",
                tokens=a_tokens,
                css=TRIAGE_CSS,
                body=body_triage(key, show_note=True),
                note=f"정렬 비교 — {cfg['label']}. 팔레트는 방향 A 고정.",
            ),
            encoding="utf-8",
        )
        made.append(p)

    # 목차 — 브라우저로 이 파일을 열면 위 전부로 갈 수 있다.
    p = OUT / "index.html"
    p.write_text(
        page(
            title="KSI 현장 지능 — 디자인 시안 목차",
            group="검토 자료",
            tokens=a_tokens,
            css=INDEX_CSS,
            body=body_index(),
            note="시안 목차 — 팔레트는 방향 A로 표시한다(목차 자체는 결정 대상이 아니다).",
        ),
        encoding="utf-8",
    )
    made.append(p)

    for m in made:
        print(f"  {m.relative_to(OUT.parent.parent)}")


if __name__ == "__main__":
    print("시안 생성:")
    build()
