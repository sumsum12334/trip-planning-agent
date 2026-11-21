import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  RECONSIDER_STORAGE_KEY,
  effectiveReconsiderEnabled,
  fetchReconsiderDefault,
  readReconsiderOverride,
  resetReconsiderDefaultCache,
  writeReconsiderOverride,
} from "./reconsider.js";

function fakeStorage(initial = {}) {
  const values = { ...initial };
  return {
    getItem: (key) => (key in values ? values[key] : null),
    setItem: (key, value) => {
      values[key] = String(value);
    },
  };
}

describe("readReconsiderOverride / writeReconsiderOverride", () => {
  it("round-trips the on/off override", () => {
    const storage = fakeStorage();
    expect(readReconsiderOverride(storage)).toBeNull();
    writeReconsiderOverride(true, storage);
    expect(storage.getItem(RECONSIDER_STORAGE_KEY)).toBe("on");
    expect(readReconsiderOverride(storage)).toBe(true);
    writeReconsiderOverride(false, storage);
    expect(storage.getItem(RECONSIDER_STORAGE_KEY)).toBe("off");
    expect(readReconsiderOverride(storage)).toBe(false);
  });

  it("treats absent or unknown values as no override", () => {
    expect(readReconsiderOverride(fakeStorage())).toBeNull();
    expect(readReconsiderOverride(fakeStorage({ [RECONSIDER_STORAGE_KEY]: "yes" }))).toBeNull();
    expect(readReconsiderOverride(null)).toBeNull();
  });

  it("survives a throwing storage", () => {
    const throwing = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
    expect(readReconsiderOverride(throwing)).toBeNull();
    expect(() => writeReconsiderOverride(true, throwing)).not.toThrow();
  });
});

describe("effectiveReconsiderEnabled", () => {
  it("prefers an explicit override over the server default", () => {
    expect(effectiveReconsiderEnabled(true, false)).toBe(false);
    expect(effectiveReconsiderEnabled(false, true)).toBe(true);
  });

  it("falls back to the server default when no override exists", () => {
    expect(effectiveReconsiderEnabled(true, null)).toBe(true);
    expect(effectiveReconsiderEnabled(false, null)).toBe(false);
  });

  it("defaults to enabled for missing or malformed server values", () => {
    expect(effectiveReconsiderEnabled(undefined, null)).toBe(true);
    expect(effectiveReconsiderEnabled(null, null)).toBe(true);
    expect(effectiveReconsiderEnabled("", null)).toBe(true);
  });
});

describe("fetchReconsiderDefault", () => {
  beforeEach(() => {
    resetReconsiderDefaultCache();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    resetReconsiderDefaultCache();
  });

  it("reads the boolean server default and caches it", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ reconsider_prompt_enabled: false }),
    });
    vi.stubGlobal("fetch", fetchMock);
    await expect(fetchReconsiderDefault()).resolves.toBe(false);
    await expect(fetchReconsiderDefault()).resolves.toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("defaults to enabled when the field is missing or the request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({}) }));
    await expect(fetchReconsiderDefault()).resolves.toBe(true);

    resetReconsiderDefaultCache();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    await expect(fetchReconsiderDefault()).resolves.toBe(true);
  });

  it("defaults to enabled on a non-ok response without caching the failure", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, json: () => Promise.resolve({}) });
    vi.stubGlobal("fetch", fetchMock);
    await expect(fetchReconsiderDefault()).resolves.toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const retryMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ reconsider_prompt_enabled: false }),
    });
    vi.stubGlobal("fetch", retryMock);
    await expect(fetchReconsiderDefault()).resolves.toBe(false);
    expect(retryMock).toHaveBeenCalledTimes(1);
  });
});
