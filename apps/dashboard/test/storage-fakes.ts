import { vi } from "vitest";

/**
 * sessionStorage quota/실패 시뮬레이션용 가짜 저장소.
 *
 * 배경: jsdom 26에서 `window.sessionStorage` 인스턴스의 프로토타입이 전역
 * `Storage.prototype`과 다르므로(`Object.getPrototypeOf(ss) !== Storage.prototype`),
 * `vi.spyOn(Storage.prototype, "setItem")`은 가로채지 못한다. 인스턴스 spy도
 * 정의가 고착되지 않아 동작하지 않는다. 대신 `vi.stubGlobal`로 저장소 자체를
 * 교체하면 bare `sessionStorage`와 `window.sessionStorage` 모두 가짜를 본다.
 *
 * 가짜는 실제 저장소 내용을 시드로 복사하고, `length`/`key(i)`/`getItem`/
 * `setItem`/`removeItem`/`clear`와 `Object.keys` 열거를 모두 지원한다.
 * 복원은 각 파일의 `afterEach(vi.unstubAllGlobals)`가 담당한다.
 */

export type StorageBehavior = {
  setItem?: (key: string, value: string, write: (key: string, value: string) => void) => void;
  getItem?: (key: string, read: (key: string) => string | null) => string | null;
  removeItem?: (key: string, remove: (key: string) => void) => void;
};

export type FakeStorageKind = "sessionStorage" | "localStorage";

function installFakeStorage(kind: FakeStorageKind, behavior: StorageBehavior = {}): { store: Map<string, string> } {
  const existing = (window as unknown as Record<string, unknown>)[kind] as Storage | undefined;
  const real: Pick<Storage, "length" | "key" | "getItem"> | undefined =
    existing && typeof existing.length === "number" ? existing : undefined;
  const store = new Map<string, string>();
  if (real) {
    for (let i = 0; i < real.length; i++) {
      const key = real.key(i);
      if (key === null) continue;
      const value = real.getItem(key);
      if (value !== null) store.set(key, value);
    }
  }
  const write = (key: string, value: string) => {
    store.set(key, String(value));
  };
  const read = (key: string) => (store.has(key) ? (store.get(key) as string) : null);
  const fake = {
    get length() {
      return store.size;
    },
    key: (index: number) => [...store.keys()][index] ?? null,
    getItem: (key: string) => (behavior.getItem ? behavior.getItem(key, read) : read(key)),
    setItem: (key: string, value: string) => {
      if (behavior.setItem) behavior.setItem(key, value, write);
      else write(key, value);
    },
    removeItem: (key: string) => {
      if (behavior.removeItem) behavior.removeItem(key, (k) => { store.delete(k); });
      else store.delete(key);
    },
    clear: () => {
      store.clear();
    },
  };
  const exposed = new Proxy(fake, {
    ownKeys: () => [...store.keys()],
    getOwnPropertyDescriptor: (_target, prop) =>
      typeof prop === "string" && store.has(prop)
        ? { configurable: true, enumerable: true, writable: true, value: store.get(prop) }
        : Reflect.getOwnPropertyDescriptor(fake, prop),
    has: (_target, prop) => (typeof prop === "string" && store.has(prop)) || Reflect.has(fake, prop),
  });
  vi.stubGlobal(kind, exposed);
  return { store };
}

export function installFakeSessionStorage(behavior: StorageBehavior = {}): { store: Map<string, string> } {
  return installFakeStorage("sessionStorage", behavior);
}

export function installFakeLocalStorage(behavior: StorageBehavior = {}): { store: Map<string, string> } {
  return installFakeStorage("localStorage", behavior);
}
