/** Navigation only: the example cannot redirect outside the materials explorer. */
export const DEFAULT_MATERIALS_DESIGN_RETURN =
  "/sites/prod-sample-floreat-01/spatial-assets?workAreaId=wa-prod-sample-floreat-01-0001";

export function materialsDesignReturnHref(value: unknown): string {
  if (typeof value !== "string" || value.length > 2048 || value !== value.trim()
    || !value.startsWith("/") || value.startsWith("//") || /[\\\x00-\x20\x7f#]/.test(value)) {
    return DEFAULT_MATERIALS_DESIGN_RETURN;
  }
  try {
    const base = "https://console.invalid";
    const url = new URL(value, base);
    if (url.origin !== base || url.pathname !== value.split("?", 1)[0]
      || !/^\/sites\/[^/]+\/spatial-assets$/.test(url.pathname)) {
      return DEFAULT_MATERIALS_DESIGN_RETURN;
    }
    return `${url.pathname}${url.search}`;
  } catch {
    return DEFAULT_MATERIALS_DESIGN_RETURN;
  }
}
