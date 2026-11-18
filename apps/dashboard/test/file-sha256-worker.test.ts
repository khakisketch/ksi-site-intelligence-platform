import { describe, expect, it } from "vitest";
import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex, utf8ToBytes } from "@noble/hashes/utils.js";
import { hashFileStream } from "@/lib/workers/file-sha256.worker";

function streamed(chunks: Uint8Array[], size = chunks.reduce((total, value) => total + value.byteLength, 0)) {
  return { size, stream: () => new ReadableStream<Uint8Array>({ start(controller) { chunks.forEach((chunk) => controller.enqueue(chunk)); controller.close(); } }) } as Pick<Blob, "size" | "stream">;
}

describe("external file hash worker", () => {
  it("hashes a known streaming vector without File.arrayBuffer", async () => {
    const chunks = [utf8ToBytes("KSI "), utf8ToBytes("external reconstruction")];
    await expect(hashFileStream(streamed(chunks), 1024)).resolves.toBe(bytesToHex(sha256(utf8ToBytes("KSI external reconstruction"))));
  });
  it("rejects an invalid chunk bound and detects a changed stream size", async () => {
    await expect(hashFileStream(streamed([new Uint8Array(2)]), 0)).rejects.toThrow("chunk size");
    await expect(hashFileStream(streamed([new Uint8Array(2)]), 9 * 1024 * 1024)).rejects.toThrow("chunk size");
    await expect(hashFileStream(streamed([new Uint8Array(2)], 3), 8)).rejects.toThrow("size changed");
  });
  it("hashes a stream chunk larger than the configured bound instead of failing (Chromium yields up to 2 MiB chunks)", async () => {
    // 실제 브라우저의 큰 파일 스트림은 1 MiB를 넘는 조각을 줄 수 있다. 같은 바이트를 작은 조각으로 준 것과 같은 해시여야 한다.
    const bytes = Uint8Array.from({ length: 2 * 1024 * 1024 + 7 }, (_, index) => (index * 31) & 0xff);
    const expected = bytesToHex(sha256(bytes));
    await expect(hashFileStream(streamed([bytes]), 1024 * 1024)).resolves.toBe(expected);
    await expect(hashFileStream(streamed([bytes.subarray(0, 3), bytes.subarray(3)]), 8)).resolves.toBe(expected);
  });
  it("reports monotonic progress across generated stream chunks", async () => {
    const progress: number[] = [];
    await hashFileStream(streamed(Array.from({ length: 128 }, () => new Uint8Array(1024))), 1024, (value) => progress.push(value));
    expect(progress).toHaveLength(128);
    expect(progress.at(-1)).toBe(128 * 1024);
  });
});
