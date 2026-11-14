"use client";

import { useOnlineStatus } from "@/hooks/useOnlineStatus";

/**
 * 전역 연결 끊김 안내 — 모든 화면의 ShellMain 최상단에 둔다.
 *
 * 온라인일 때는 아무것도 그리지 않는다. 오프라인일 때만 한 줄 배너를
 * 보여주고, 입력 보존(초안·동결)과 "연결 후 다시 시도"라는 다음 행동을
 * 함께 둔다. 각 폼의 실패 문구가 "왜 안 되는지"를 설명하지 못할 때 이
 * 배너가 그 이유를 대신한다. 성공 토스트와 달리 영속 표시다 — 연결이
 * 돌아오면 자동으로 사라진다.
 */
export function ConnectivityNotice() {
  const online = useOnlineStatus();
  if (online) return null;
  return (
    <div role="alert" data-connectivity-notice="offline" className="m-3 rounded-lg border border-line-strong bg-surface px-4 py-3 text-body leading-5 text-ink-1">
      <p className="font-bold">연결이 끊겼습니다. 전송·저장 확인은 연결 후에 다시 시도하세요.</p>
      <p className="mt-1 text-ink-2">입력한 내용과 준비된 요청은 이 탭에 그대로 있습니다. 새로고침하면 사라질 수 있으니 연결이 돌아온 뒤 같은 화면에서 다시 시도하세요.</p>
    </div>
  );
}
