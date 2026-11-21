// "Ask AI to reconsider after plan edits" preference.
// Effective value = server default (GET /api/settings → reconsider_prompt_enabled,
// default true) unless the user overrode it in this browser (localStorage
// "reconsiderPromptEnabled": "on" / "off"; absent key = follow server default).

export const RECONSIDER_STORAGE_KEY = "reconsiderPromptEnabled";

const safeStorage = () => {
  try {
    return typeof window !== "undefined" && window.localStorage ? window.localStorage : null;
  } catch {
    return null;
  }
};

// Returns true/false when the user overrode the server default, otherwise null.
export function readReconsiderOverride(storage = safeStorage()) {
  try {
    const value = storage?.getItem(RECONSIDER_STORAGE_KEY);
    if (value === "on") return true;
    if (value === "off") return false;
  } catch {
    /* storage unavailable */
  }
  return null;
}

export function writeReconsiderOverride(enabled, storage = safeStorage()) {
  try {
    storage?.setItem(RECONSIDER_STORAGE_KEY, enabled ? "on" : "off");
  } catch {
    /* storage unavailable */
  }
}

export function effectiveReconsiderEnabled(serverDefault, override) {
  if (override === true || override === false) return override;
  return serverDefault !== false;
}

let cachedServerDefault = null;
let inflight = null;

export function resetReconsiderDefaultCache() {
  cachedServerDefault = null;
  inflight = null;
}

// Fetches the server default once and caches it. A failed or malformed fetch
// resolves to true (enabled) and is not cached, so a later mount can retry.
export async function fetchReconsiderDefault() {
  if (cachedServerDefault != null) return cachedServerDefault;
  if (!inflight) {
    inflight = (async () => {
      try {
        const response = await fetch("/api/settings");
        if (response.ok) {
          const data = await response.json();
          if (typeof data?.reconsider_prompt_enabled === "boolean") {
            cachedServerDefault = data.reconsider_prompt_enabled;
          }
        }
      } catch {
        /* fall through to the enabled default */
      } finally {
        inflight = null;
      }
      return cachedServerDefault ?? true;
    })();
  }
  return inflight;
}
