export type HashResult = { file: File; sha256: string; size: number };

function abortError(): DOMException { return new DOMException("Operation was aborted", "AbortError"); }

/** 파일 전체의 SHA-256을 워커에서 청크로 계산한다. 파일은 브라우저 밖으로 나가지 않는다. */
export async function hashFile(file: File, workers: Set<Worker>, onProgress: (bytes: number) => void, signal: AbortSignal): Promise<HashResult> {
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL("./workers/file-sha256.worker.ts", import.meta.url));
    let settled = false;
    let onAbort: () => void = () => undefined;
    const finish = () => {
      workers.delete(worker);
      worker.terminate();
      signal.removeEventListener("abort", onAbort);
    };
    const settle = (result: { value: HashResult } | { error: Error }) => {
      if (settled) return;
      settled = true;
      finish();
      if ("error" in result) reject(result.error);
      else resolve(result.value);
    };
    onAbort = () => settle({ error: abortError() });
    workers.add(worker);
    signal.addEventListener("abort", onAbort, { once: true });
    if (signal.aborted) {
      onAbort();
      return;
    }
    const id = crypto.randomUUID();
    worker.onmessage = ({ data }) => {
      if (data.id !== id) return;
      if (typeof data.progress === "number") onProgress(data.progress);
      if (data.error) settle({ error: new Error(data.error) });
      if (data.sha256) settle({ value: { file, sha256: data.sha256, size: data.size } });
    };
    worker.onerror = () => settle({ error: new Error("file hashing failed") });
    worker.postMessage({ id, file, chunkBytes: 1024 * 1024 });
  });
}
