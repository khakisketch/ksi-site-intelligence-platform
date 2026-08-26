export function safeNextPath(raw: string): string {
  try {
    const parsed = new URL(raw, "http://ksi-dashboard.invalid");
    if (parsed.origin !== "http://ksi-dashboard.invalid") return "/";
    const path = `${parsed.pathname}${parsed.search}${parsed.hash}`;
    if (!path.startsWith("/") || path.startsWith("//")) return "/";
    return path;
  } catch {
    return "/";
  }
}
