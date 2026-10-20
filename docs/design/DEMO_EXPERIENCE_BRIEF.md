# Design-first demonstration: place → observations → uses → evidence

Status: **primary story and five-step flow confirmed by Human**, 2026-10-20; screen composition remains a review proposal. No product UI implementation
or server/data mutation in this design pass. Audience confirmed by Human: **일반 소개·사업 관계자**.
This is a subordinate design brief selected by the current rebaseline task ledger, not a new
product definition, approval to publish or completion claim.

## Outcome before features

Human: “무작정 기능 구현보다는 화면 UI UX 설계 사용 흐름 체계적으로 세우고 기능 개발…
실제 다운로드 혹은 외부에서든 간에 구한 것들로 자료 채워서 실제 그런 데모… 남 보여줘도 이해”.

The demonstration should let a nontechnical viewer explain **what place this is, what observations
exist, what they may be used for, and where the evidence comes from** without a developer narrating
every screen. A 3–5 minute walkthrough is a proposed design target, not a measured completion time.
Uploading one's own data is a second journey, not the entry requirement for understanding the service.

Costly failures: unrelated photos mistaken for site evidence; image differences sold as volume results;
synthetic results attached to a real site; technical IDs replacing a story; an attractive first screen
ending at unavailable analysis; a showable prototype mistaken for a working production service.

## Current product observation (fresh, not old golden screenshots)

Inspected current source `c0ece080` and live private staging `:10000`, authenticated as a development
operator. This is not customer testing. Native Browser captured Home; later Native captures failed
visibility checks even after focus, so isolated Playwright captured the remaining states.
Settled screenshots were awaited past streamed skeletons. Evidence:
`/tmp/opencode/ksi-demo-flow-20261020/ui/`, `ready-observations.json` and `*-ready.png`.

| Observation | User impact | Design response |
|---|---|---|
| Home leads with missing-source warnings and an E2E approval card without observation imagery. | The first message is environment health, not the service's value. | A scoped demonstration entry opens a prepared case, without changing normal Home's no-duplicate-work-queue contract. Resolve real dependencies in the eventual demo; never hide errors with fake success. |
| Six sites mix E2E fixtures and an empty beta-test site, all with labelled decorative covers. | Business viewers must guess which case to open. | Present one intentional primary example; retain an explicitly separate synthetic calculation example. Do not rename E2E fixtures as customer projects. |
| Site detail shows a generic polygon, a separate material list, several side summaries and unavailable analysis records. | No immediate connection between a real place, a date and a selected artifact. | Select the demonstration's area/observation explicitly and consistently; pair the actual image with its date and material facts. |
| Materials begins by asking for a work area even when the site has one. | A new viewer encounters configuration before content. | Preserve scoped URLs when moving between site, material and analysis views; avoid discarding a known selection. More than one area still gets an explicit picker. |
| Analysis ends at “이 환경에서는 현장 변화 분석 기능을 사용할 수 없습니다.” | The promised walkthrough cannot finish. | Do not make the demo's first path require unavailable runtime. Present actual evidence boundaries and a separately labelled completed synthetic workflow only where its real Core records are mounted. |

Preserve: site-local five-area navigation, restrained visual system, clear missing-data messaging,
technical details behind disclosure, card/list choice, mobile reading, no fake preview and no second
work queue on Home. Neither the fixture-only status vocabulary nor the current layout is a contract
requiring a viewer to understand acquisition internals.

## Two journeys, one product

**Introduction (primary for this task)**

`Prepared example → place + dated observations → same-place visual comparison → what can be
verified / what cannot → evidence and source → optional synthetic calculation workflow → feedback`.

**Operator (existing journey, secondary in the demo)**

`Own site/area → create observation work → submit bytes → inspect → use-specific decision →
permitted analysis/data use → review → next observation`.

Do not force business viewers to enter CRS, producer versions or area polygons before they see a
useful example. Do not replace operator UI with a marketing slide deck. A brief guide must be
dismissible, have back/continue and retain context; its order does not grant access or approve a result.

## Screen anatomy and information hierarchy

| Screen | Main question / persistent content | Primary action | Supporting disclosure |
|---|---|---|---|
| 1. Example entry | “무슨 서비스인가?” One short product sentence, one real case preview, publisher/place/date, actual-data label. Separate synthetic-case label. | `사례 현장 보기` | Source/licence; alternative `내 자료로 시작하기` after the example, not as the dominant entry action. |
| 2. Place overview | “어디를 언제 관측했나?” Large real orthomosaic of Floreat-f3, selected area (authored demo selection labelled as such, never a surveyed boundary), two observation dates and material counts derived from the manifest. | `두 시점 보기` | Original file facts and resolution. Layer names explain 정사영상=보이는 표면, DSM=표면 높이 자료. |
| 3. Observation comparison | “같은 장소를 어떻게 다시 보나?” Two actual images, common extent, two publisher-declared dates; synced view / optional before-after control. Label display alignment and unmeasured status. | `이 자료로 가능한 활용 확인` | Layer switch for DSM surface-form view with shared colour scale. No auto change hotspot, volume, accuracy grade or invented anomaly. |
| 4. Uses and limits | “무엇을 할 수 있고 왜 제한되나?” Distinguish original-source preview, actual Core inspection and analysis admission. This pass's public pair: no observed vertical reference; unsupported quantitative CRS policy is an additional constraint. | `근거·원본 확인` | Core blocker/details when actually read. Missing configured runtime is environment failure, not a verdict about the file. A locally derived preview is not Core-published imagery. |
| 5. Evidence / next step | “믿을 근거와 다음 행동은?” Source, declared vs byte-observed facts, original/derived relationship, versions/digests, original-source downloads with filename/size/licence. | `계산·검토 흐름 예시 보기` or `의견 남기기` | API/MCP common-record details for technical visitors. Feedback initially session notes/manual collection; no hidden analytics or new personal-data collection. |

The 5-screen sequence is a narrative over existing site-local records, not five new top-level menus.
One persistent breadcrumb (“사례 / 장소 / 관측 시점”) and one next action should carry orientation.
Do not turn all statuses/diagnostics into permanent dashboard cards. On desktop, image + narrow
context panel; on mobile, source/date first, image next, comparison with labelled switching or stacked
panels rather than two tiny maps. Keep <1024px mutation restrictions. Date/layer controls must work
without dragging, be keyboard reachable and explain their selected state in text.

## Real case and synthetic workflow must never merge

**Real primary case, ready as material:** Cambridge Coastcare's Floreat-f3, Western Australia.
Two observations, publisher-declared 2021-08-17 and 2022-08-24; two orthomosaics + two DSMs.
All four file identities and licence sources are in `DEMO_MATERIALS.json`.

- Actual coast/dunes, **not a construction project**. There is no customer testimonial, work order,
  GCP, surveyed boundary, measured change or customer acceptance here.
- T0 ortho is a GeoTIFF; T1 ortho is JPEG2000. The JPEG2000 source is design material, **not a claim
  that the product accepts JP2 submissions**. Product registration needs owner-supported format and
  declared derivation if a view is converted. Never relabel converted bytes as the original.
- Common-bounds imagery previews are authored derivatives for viewing, not product registration,
  product orthorectification, geodetic alignment validation or a quantitative difference map.
- Original DSMs lack observed vertical reference and use EPSG:7850. Do not fabricate a compound CRS
  to enable volume. Do not import the old out-of-product reference calculation as a KSI result.

**Separate secondary case, proposal:** an explicitly labelled generated 3-epoch terrain example
with actual Core/inspector/worker records. Show input pair → numeric result (provisional where applicable)
→ evidence → human review → next pair, previous history retained. Prefer a meaningful, verified
synthetic extent over a 2×2 test-fixture headline. Do not invent impressive quantities as business proof.
The intro and persistent case label must state “합성 데이터 · 계산·검토 절차 예시”. Never overlay
these numbers onto the real Floreat imagery. If that runtime is absent, do not present a fake run button.

## State and return-path contracts

- One observation: view it; explain why a pair cannot be selected. Zero results is not zero volume.
- File valid / quantitative use blocked: keep allowed views and reasons; no all-green aggregate badge.
- Environment unavailable: persistent in-place error with retry and return to materials, never “file invalid”.
- Preview absent: retain filename/date/source with a truthful no-preview state.
- No permission / revoked / foreign case: refuse through existing authority; no static-file bypass to
  customer bytes and no shared ADMIN account used as a public beta identity.
- Back/reload/deep-link: preserve selected case, work area, date and layer. Never silently change
  which two observations a result concerns.
- A newer observation: neutral relationship only; earlier record is not “superseded” or made unsuitable.

## Development order after design confirmation

1. Confirm this scenario and screen relationships; prepare annotated screen layouts using these real
   assets, preserving incumbent identity. This design pass does not patch production UI.
2. Implement ONE representative slice: prepared-case entry → place → actual source preview →
   date comparison → source/limit details. Inspect desktop and mobile together; a sample-data manifest
   is not runtime evidence. Keep demo explicitly separate from E2E and customer data.
3. Connect necessary existing Core reads and the isolated demonstration dataset through supported
   ingress; add only capabilities needed by the chosen journey. Inspection runtime is a dependency
   to a real verdict, not a licence to fake one. Do not mutate old rig records.
4. Add the distinct synthetic calculation/review continuation, verify result/authority/history and
   downloads through real endpoints; API/MCP parity uses the same records.
5. Use the completed journey with new viewers and record where explanation/help was needed before
   expanding features. Public beta deployment, customer uploads/retention and actual IdP stay gated.

## Proposed acceptance (not yet measured)

- A first-time viewer can identify real versus synthetic case, place and observation dates without help.
- They can reach two actual dated views, source/licence and quantitative restriction without a dead end.
- They can explain what KSI adds beyond showing an image: scoped evidence, use-specific decisions,
  reproducible results and recurring records. The synthetic case illustrates the latter without claiming
  real-terrain accuracy.
- Source download links fetch the advertised original file; converted/preview bytes have separate
  identity and modification notes. Screenshots alone do not establish download behaviour.
- Relevant back/reload/loading/unavailable/permission and 390/1440 layouts are exercised on the
  actual resulting build; keyboard navigation as well as pointer interaction is verified.

## Implementation planning boundary

Requirement IDs: SDP-REQ-01/02/04/05/06/08, ADR-KSI-025/026/036/037/038/039.
Owner module: `apps/dashboard/` for presentation; Core remains read/write authority.
Contracts affected: none in this design pass. Any future change must first map the existing owner contracts.
Reference assets: actual DataWA files (CC BY 4.0); current Console captures; no reference code reuse.
Adoption decisions: existing site workspace + progressive disclosure; explicit prepared-case entry rather
than duplicate Home queue. Retool's live-demo entry and monday.com's populated example were inspected
as narrow examples of 'show before setup', not copied as GIS UI or brand assets.
References inspected: [Retool live-demo entry](https://mobbin.com/sites/sections/3096a8b6-62c8-48d2-be2a-76dfe48e8ee6)
and [monday.com populated interaction](https://mobbin.com/sites/sections/cb5efa4f-8757-45c7-a26f-ffadd272a4fb).
The marketing feature/collage results and facility-photo overlay were rejected as unsuitable evidence
for an actual observation/comparison workflow.
Files in this pass: this brief, material manifest, app-context pointer and append-only existing task ledger.
Tests: repository boundary/normalization and diff checks for documents; no claim of implemented UI tests.
HIL/real-device assumptions: none; no field accuracy implied.
License/data implications: source attribution retained, originals read-only/ignored by Git, no customer upload
or AI-egress policy changes. INV-040 (no fabricated facts); INV-050/051 (processing/data lineage),
INV-060/061 (scope and AI tool boundaries) remain unchanged.
Rollback: remove the proposed design documents/reading aid and newly downloaded optional files only;
do not reset servers, delete old originals/fixtures or alter product-state/milestone pins.

## Confirmed direction / review boundary

Human selected **실제 해안 관측 + 별도 계산 예시** after seeing the five-screen proposal and the real
same-bounds imagery sheet. This confirms the audience, scenario and broad sequence, not a claim that
any file has been registered in the service. A clickable screen-structure study is being prepared as `demo-screen-study.html`, with a persistent
design-only/no-server-connection label. Product feature work follows
review of that screen study; no unsupported measurement can be made true by presentation.

Further observed label risk: the current list says “관측 시작 전” on a site already containing two
observation works. This is an inference from legacy UNMAPPED, not an observation fact. In the new
case view show actual dated observation counts from scoped records (or explicitly from the offline
source manifest in the design study), not a legacy acquisition-state label presented as material status.
Do not change the underlying domain state machine to make a screenshot look complete.


## Screen-study delivery and review evidence

Open [the interactive screen study](demo-screen-study.html). It is a self-contained design proposal
with embedded actual display crops, not a live connected application. Original source links deliberately
leave for DataWA; optional notes are not saved/sent. Full-size 1440 and390 renders and keyboard/date/
layer/back/reload checks are recorded in `/tmp/opencode/ksi-demo-flow-20261020/study-final/`.
The final packaged document was rendered and inspected; desktop selected-layer view has two images,
mobile single-date view has one. No horizontal overflow or page errors in this coverage. New viewers'
actual understanding and production behaviour remain unverified. Product feature implementation has
not begun in this pass: composition can still be changed cheaply before connecting runtime dependencies.
