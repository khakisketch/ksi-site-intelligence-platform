/** Display-only context for a deliberately isolated, synthetic local rehearsal.
 * This marker grants no permissions, skips no checks, and changes no data.
 */
export function SyntheticDemoNotice({
  deploymentProfile,
  marker,
}: {
  deploymentProfile: string;
  marker?: string;
}) {
  if (deploymentProfile !== "LOCAL" || marker !== "1") return null;
  return (
    <aside aria-label="합성 자료 시연 안내" className="border-b border-line bg-sunk px-4 py-2 text-[12px] leading-5 text-ink-2 sm:px-5">
      <strong className="font-semibold text-ink-1">합성 자료 시연</strong>
      <span> · 화면과 업무 절차 확인용이며, 실제 현장 측정값이 아닙니다.</span>
    </aside>
  );
}
