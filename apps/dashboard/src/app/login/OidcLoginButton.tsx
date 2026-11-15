"use client";

import { useFormStatus } from "react-dom";

// OIDC 로그인은 서버 액션이 외부 발급자로 리다이렉트한다. 이동이 끝날 때까지
// pending이 유지되므로, 그 동안 버튼을 잠가 같은 요청이 두 번 나가지 않게 하고
// 눌렀다는 반응을 보인다.
export function OidcLoginButton({
  label,
  pendingLabel = "이동 중...",
  className,
}: {
  label: string;
  pendingLabel?: string;
  className: string;
}) {
  const { pending } = useFormStatus();

  return (
    <button type="submit" disabled={pending} aria-busy={pending} className={className}>
      {pending ? pendingLabel : label}
    </button>
  );
}
