/** A cryptographically random UUID v4, including on non-secure local HTTP.
 * Throws if neither browser CSPRNG API is available; never uses Math.random. */
export function workAreaUuid(): string {
  const source = globalThis.crypto;
  if (!source) throw new Error('CSPRNG unavailable');
  if (typeof source.randomUUID === 'function') {
    try {
      const id = source.randomUUID();
      if (/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(id)) return id;
    } catch { /* Insecure contexts may reject randomUUID. */ }
  }
  if (typeof source.getRandomValues !== 'function') throw new Error('CSPRNG unavailable');
  const bytes = new Uint8Array(16);
  source.getRandomValues(bytes);
  bytes[6] = (bytes[6]! & 0x0f) | 0x40;
  bytes[8] = (bytes[8]! & 0x3f) | 0x80;
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}
