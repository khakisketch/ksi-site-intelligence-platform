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
  it("enforces a bounded chunk and detects a changed stream size", async () => {
    await expect(hashFileStream(streamed([new Uint8Array(9)]), 8)).rejects.toThrow("chunk");
    await expect(hashFileStream(streamed([new Uint8Array(2)], 3), 8)).rejects.toThrow("size changed");
  });
  it("reports monotonic progress across generated stream chunks", async () => {
    const progress: number[] = [];
    await hashFileStream(streamed(Array.from({ length: 128 }, () => new Uint8Array(1024))), 1024, (value) => progress.push(value));
    expect(progress).toHaveLength(128);
    expect(progress.at(-1)).toBe(128 * 1024);
  });
});
