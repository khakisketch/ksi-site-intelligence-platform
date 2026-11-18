import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";

type StreamedFile = Pick<Blob, "size" | "stream">;
type HashRequest = { id: string; file: File; chunkBytes: number };

export async function hashFileStream(file: StreamedFile, chunkBytes: number, onProgress?: (bytes: number) => void): Promise<string> {
  if (!Number.isSafeInteger(chunkBytes) || chunkBytes < 1 || chunkBytes > 8 * 1024 * 1024) {
    throw new TypeError("invalid hash chunk size");
  }
  const hash = sha256.create();
  let offset = 0;
  const reader = file.stream().getReader();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!value) throw new Error("hash chunk missing");
      // 브라우저는 큰 파일 스트림에서 설정한 크기보다 큰 조각(Chromium은 최대 2 MiB)을 줄 수 있다. 조각을
      // 거부하면 큰 파일이 전부 해시에 실패하므로, 이미 읽은 조각을 설정한 크기 이하로 나눠 해시기에 넣는다.
      for (let at = 0; at < value.byteLength; at += chunkBytes) hash.update(value.subarray(at, Math.min(at + chunkBytes, value.byteLength)));
      offset += value.byteLength;
      onProgress?.(offset);
    }
  } finally {
    reader.releaseLock();
  }
  if (offset !== file.size) throw new Error("file stream size changed while hashing");
  return bytesToHex(hash.digest());
}

const workerScope = globalThis as typeof globalThis & {
  postMessage?: (message: unknown) => void;
  onmessage?: (event: MessageEvent<HashRequest>) => void;
};
if (typeof workerScope.postMessage === "function") {
  const post = workerScope.postMessage.bind(workerScope);
  workerScope.onmessage = async (event: MessageEvent<HashRequest>) => {
    const { id, file, chunkBytes } = event.data;
    try {
      const digest = await hashFileStream(file, chunkBytes, (progress) => post({ id, progress }));
      post({ id, sha256: digest, size: file.size });
    } catch {
      post({ id, error: "file hashing failed" });
    }
  };
}
