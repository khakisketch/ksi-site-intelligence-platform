import { describe, expect, it } from 'vitest';
import { readWorkAreaRecord, writeWorkAreaRecord } from '../src/app/sites/[siteId]/work-areas/work-area-session-storage';

const identity = `v1-${'a'.repeat(64)}`;
const other = `v1-${'b'.repeat(64)}`;
const record = { version: 1 as const, siteId: 'site-1', identity, payload: { name: '37.00x', vertices: [], correctionId: null, correctionReady: false, snapshot: null } };

describe('work area tab storage', () => {
  it('round trips exact data only for its site and verified identity', () => {
    const storage = new MapStorage();
    expect(writeWorkAreaRecord(storage, record)).toBe(true);
    expect(readWorkAreaRecord(storage, 'site-1', identity)).toEqual({ kind: 'found', record });
    expect(readWorkAreaRecord(storage, 'site-1', other)).toEqual({ kind: 'empty' });
    expect(readWorkAreaRecord(storage, 'site-2', identity)).toEqual({ kind: 'empty' });
    expect(readWorkAreaRecord(storage, 'site-1', null)).toEqual({ kind: 'unverified' });
  });
  it('does not overwrite corrupt or unsupported existing data', () => {
    const storage = new MapStorage();
    expect(writeWorkAreaRecord(storage, record)).toBe(true);
    const key = [...storage.values.keys()][0];
    for (const raw of ['not json', JSON.stringify({ ...record, version: 2 })]) {
      storage.setItem(key, raw);
      expect(readWorkAreaRecord(storage, 'site-1', identity)).toEqual({ kind: 'invalid' });
      expect(writeWorkAreaRecord(storage, record)).toBe(false);
      expect(storage.getItem(key)).toBe(raw);
    }
  });
  it('never replaces mismatched or incomplete and future payloads', () => {
    const storage = new MapStorage();
    expect(writeWorkAreaRecord(storage, record)).toBe(true);
    const key = [...storage.values.keys()][0];
    for (const invalid of [
      { ...record, siteId: 'site-other' }, { ...record, identity: other },
      { ...record, extra: 1 }, { ...record, payload: { ...record.payload, future: 1 } },
      { ...record, payload: { name: 'raw' } },
      { ...record, payload: { ...record.payload, snapshot: { rows: [{lat:'x',lon:'',future:true}], rejectedDraws: [] } } },
    ]) {
      const raw = JSON.stringify(invalid);
      storage.setItem(key, raw);
      expect(readWorkAreaRecord(storage, 'site-1', identity)).toEqual({ kind: 'invalid' });
      expect(writeWorkAreaRecord(storage, record)).toBe(false);
      expect(storage.getItem(key)).toBe(raw);
    }
  });
  it('fails closed on read and write exceptions', () => {
    const storage = new MapStorage();
    storage.failRead = true;
    expect(readWorkAreaRecord(storage, 'site-1', identity)).toEqual({ kind: 'unavailable' });
    expect(writeWorkAreaRecord(storage, record)).toBe(false);
    storage.failRead = false;
    storage.failWrite = true;
    expect(writeWorkAreaRecord(storage, record)).toBe(false);
  });
});

class MapStorage {
  values = new Map<string, string>();
  failRead = false;
  failWrite = false;
  getItem(key: string) { if (this.failRead) throw new Error('read'); return this.values.get(key) ?? null; }
  setItem(key: string, value: string) { if (this.failWrite) throw new Error('quota'); this.values.set(key, value); }
}
