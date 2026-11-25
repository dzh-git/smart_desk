import { describe, expect, it } from "vitest";
import { getSceneChange, getTheme, seatAngle, type SpatialState } from "../sceneState";

const live: SpatialState = { mode: "room", phase: "live", level: 0.4 };

describe("SmartDesk scene state", () => {
  it("warps when the actual workspace or route changes", () => {
    expect(getSceneChange(live, { ...live, mode: "agenda" })).toBe("warp");
    expect(getSceneChange(live, { ...live, mode: "station" })).toBe("warp");
  });

  it("uses a bounded pulse for actual state changes and ignores equivalent polling", () => {
    expect(getSceneChange(live, { ...live })).toBe("none");
    expect(getSceneChange(live, { ...live, selectedSeat: 3 })).toBe("burst");
    expect(getSceneChange(live, { ...live, phase: "vote" })).toBe("burst");
    expect(getSceneChange(live, { ...live, phase: "complete" })).toBe("dissolve");
  });

  it("preserves nine distinct angular seat positions and gives workflow phases their own palette", () => {
    const angles = Array.from({ length: 9 }, (_, index) => seatAngle(index + 1));
    expect(new Set(angles).size).toBe(9);
    expect(getTheme(live).accent).not.toBe(getTheme({ ...live, phase: "vote" }).accent);
    expect(getTheme(live).accent).not.toBe(getTheme({ ...live, mode: "service" }).accent);
  });
});
