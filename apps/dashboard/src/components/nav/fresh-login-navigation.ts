// This marker is private to this transition, never a draft or account identifier.
// It prevents a redirect/proxy defect from producing a full-document loop.
const MARKER = "ksi.login-fresh-document.v1";

type FreshLoginBrowser = {
  location: Pick<Location, "pathname" | "reload">;
  sessionStorage: Pick<Storage, "getItem" | "setItem">;
};

export function loadFreshLoginDestination(pathname: string, browser: FreshLoginBrowser = window): boolean {
  if (browser.location.pathname !== pathname) return false;
  try {
    if (browser.sessionStorage.getItem(MARKER) === "pending") return false;
    browser.sessionStorage.setItem(MARKER, "pending");
  } catch {
    return false;
  }
  try {
    // replace(href) can be a same-document navigation when href has a fragment.
    // Reload requests a fresh document while preserving path, query and hash.
    browser.location.reload();
    return true;
  } catch {
    return false;
  }
}

export function completeFreshLoginDestination() {
  try { window.sessionStorage.removeItem(MARKER); } catch { /* storage unavailable: no transition was armed */ }
}

// Explicit recovery can proceed even if storage is unavailable or the automatic
// guard is armed. This preserves the full current URL, including its fragment.
export function manuallyReloadFreshLoginDestination(): void {
  window.location.reload();
}
