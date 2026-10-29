import { describe, expect, it } from "vitest";

// Core bootstrap 멱등 범위는 (organization, actor, requestKey)다 — key만으로는
// 전역 유일하지 않다. 같은 key라도 원래 신원이 다르면 별도 기록으로 보존하고,
// 어느 쪽의 성공·삭제도 타 주체의 것을 지우거나 귀속을 바꾸지 않는다.
import {
  removePriorUnknown,
  upsertPriorUnknown,
  type PriorUnknownRequest,
} from "@/lib/site-registration/shared";

const ALICE = `v1-${"a".repeat(64)}`;
const BOB = `v1-${"b".repeat(64)}`;

function entry(overrides: Partial<PriorUnknownRequest> = {}): PriorUnknownRequest {
  return {
    kind: "mapped",
    key: "11111111-2222-4333-8444-555555555555",
    originFingerprint: ALICE,
    payloadDigest: "{}",
    name: "현장 A",
    ...overrides,
  };
}

describe("priorUnknowns 신원 결속 (key 충돌)", () => {
  it("같은 kind+key라도 원래 신원이 다르면 둘 다 보존한다 (A가 삭제되지 않는다)", () => {
    const afterAlice = upsertPriorUnknown(undefined, entry());
    expect(afterAlice).toHaveLength(1);

    const afterBob = upsertPriorUnknown(
      afterAlice,
      entry({ originFingerprint: BOB, name: "현장 B" }),
    );
    expect(afterBob).toHaveLength(2);
    expect(afterBob[0]).toMatchObject({ originFingerprint: BOB, name: "현장 B" });
    expect(afterBob[1]).toMatchObject({ originFingerprint: ALICE, name: "현장 A" });
  });

  it("같은 (kind, key, origin, digest)는 하나로 합친다", () => {
    const once = upsertPriorUnknown(undefined, entry());
    const twice = upsertPriorUnknown(once, entry({ name: "현장 A2" }));
    expect(twice).toHaveLength(1);
    expect(twice[0]).toMatchObject({ payloadDigest: "{}", name: "현장 A2" });
  });

  it("같은 (kind, key, origin)이라도 digest가 다르면 별개로 보존한다", () => {
    const once = upsertPriorUnknown(undefined, entry());
    expect(once).toHaveLength(1);
    const twice = upsertPriorUnknown(once, entry({ payloadDigest: '{"v":2}', name: "바뀐 현장" }));
    expect(twice).toHaveLength(2);
    expect(twice[0]).toMatchObject({ payloadDigest: '{"v":2}' });
    expect(twice[1]).toMatchObject({ payloadDigest: "{}" });
  });

  it("성공·삭제는 같은 origin 항목만 지우고 타 주체는 남긴다", () => {
    const list = upsertPriorUnknown(
      upsertPriorUnknown(undefined, entry()),
      entry({ originFingerprint: BOB, name: "현장 B" }),
    );
    expect(list).toHaveLength(2);

    const afterAliceDone = removePriorUnknown(list, "mapped", entry().key, ALICE, entry().payloadDigest);
    expect(afterAliceDone).toHaveLength(1);
    expect(afterAliceDone[0]).toMatchObject({ originFingerprint: BOB });
  });

  it("origin이 다르면 아무것도 지우지 않는다", () => {
    const list = upsertPriorUnknown(undefined, entry());
    const untouched = removePriorUnknown(list, "mapped", entry().key, BOB, entry().payloadDigest);
    expect(untouched).toHaveLength(1);
    expect(untouched[0]).toMatchObject({ originFingerprint: ALICE });
  });

  it("kind가 다르면 같은 key라도 별개 기록이다", () => {
    const list = upsertPriorUnknown(
      upsertPriorUnknown(undefined, entry()),
      entry({ kind: "legacy", originFingerprint: ALICE }),
    );
    expect(list).toHaveLength(2);
    const afterMappedDone = removePriorUnknown(list, "mapped", entry().key, ALICE, entry().payloadDigest);
    expect(afterMappedDone).toHaveLength(1);
    expect(afterMappedDone[0]?.kind).toBe("legacy");
  });

  it("원본 지문 없는 항목은 어떤 지문으로도 지우지 않는다", () => {
    const list = upsertPriorUnknown(undefined, { ...entry(), originFingerprint: undefined });
    expect(list).toHaveLength(1);
    expect(removePriorUnknown(list, "mapped", entry().key, ALICE, entry().payloadDigest)).toHaveLength(1);
    expect(removePriorUnknown(list, "mapped", entry().key, BOB, entry().payloadDigest)).toHaveLength(1);
  });

  it("성공은 같은 digest 항목만 해소하고 다른 내용의 같은 키·주체는 남긴다", () => {
    const list = upsertPriorUnknown(
      upsertPriorUnknown(undefined, entry()),
      entry({ payloadDigest: '{"v":2}', name: "바뀐 현장" }),
    );
    expect(list).toHaveLength(2);
    const afterV1Done = removePriorUnknown(list, "mapped", entry().key, ALICE, '{}');
    expect(afterV1Done).toHaveLength(1);
    expect(afterV1Done[0]).toMatchObject({ payloadDigest: '{"v":2}' });
  });

  it("digest가 다르면 같은 origin이라도 지우지 않는다", () => {
    const list = upsertPriorUnknown(undefined, entry({ payloadDigest: '{"v":1}' }));
    const kept = removePriorUnknown(list, "mapped", entry().key, ALICE, '{"v":2}');
    expect(kept).toHaveLength(1);
    expect(kept[0]).toMatchObject({ payloadDigest: '{"v":1}', name: "현장 A" });
  });
});
