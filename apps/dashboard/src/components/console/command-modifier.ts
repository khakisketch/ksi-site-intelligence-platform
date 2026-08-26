"use client";

import { useSyncExternalStore } from "react";

export type CommandModifierLabel = "⌘" | "Ctrl";

export function commandModifierLabel(platform: string): CommandModifierLabel {
  return /Mac|iPhone|iPad|iPod/i.test(platform) ? "⌘" : "Ctrl";
}

/**
 * Server rendering uses the non-Mac label because it is the least surprising
 * default for this Linux-hosted console. Apple clients correct it after
 * hydration without changing the shortcut itself (both Cmd+K and Ctrl+K work).
 */
function subscribeToPlatform(): () => void {
  return () => undefined;
}

export function useCommandModifierLabel(): CommandModifierLabel {
  return useSyncExternalStore(
    subscribeToPlatform,
    () => commandModifierLabel(navigator.platform),
    () => "Ctrl",
  );
}
