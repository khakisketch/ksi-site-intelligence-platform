"use client";

import { useActionState } from "react";

import { login, type LoginState } from "./actions";

const INITIAL_STATE: LoginState = {};

export function LoginForm({ next }: { next: string }) {
  const [state, formAction, pending] = useActionState(login, INITIAL_STATE);

  return (
    <form action={formAction} className="flex flex-col gap-4">
      <input type="hidden" name="next" value={next} />
      <div className="flex flex-col gap-1.5">
        <label htmlFor="token" className="text-sm font-medium break-keep">
          Bearer 토큰
        </label>
        <input
          id="token"
          name="token"
          type="password"
          autoComplete="off"
          autoFocus
          required
          aria-invalid={state.error ? "true" : undefined}
          className="input"
        />
      </div>
      {state.error && (
        <p role="alert" className="break-keep text-sm text-crit-ink">
          {state.error}
        </p>
      )}
      <button type="submit" disabled={pending} className="btn btn-primary mt-2 w-full">
        {pending ? "확인 중..." : "로그인"}
      </button>
    </form>
  );
}
