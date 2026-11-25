import type { SceneQuality } from "./sceneState";

const KEY = "smartdesk.spatial.preferences.v1";

export interface SpatialPreferences {
  quality: SceneQuality;
  reducedMotion: boolean;
}

const defaults: SpatialPreferences = { quality: "auto", reducedMotion: false };

export function readPreferences(): SpatialPreferences {
  try {
    const stored = JSON.parse(localStorage.getItem(KEY) ?? "null");
    if (stored && ["auto", "high", "medium", "low"].includes(stored.quality)) {
      return { quality: stored.quality, reducedMotion: stored.reducedMotion === true };
    }
  } catch {
    // Browser storage can be disabled, especially in embedded WebViews.
  }
  return defaults;
}

export function savePreferences(preferences: SpatialPreferences): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(preferences));
  } catch {
    // Graphics preferences remain available for the current page.
  }
}
