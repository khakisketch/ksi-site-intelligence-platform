/** 응답 본문을 안전하게 JSON으로 읽는다 — 본문이 없거나 JSON이 아니어도 예외를 던지지 않는다. */
export async function parseJsonSafe<T>(response: Response): Promise<Partial<T>> {
  try {
    return (await response.json()) as T;
  } catch {
    return {};
  }
}
