import { describe, expect, it } from "vitest";
import { createDirector } from "../director";
import type { SpatialState } from "../sceneState";

const room: SpatialState = { mode: "room", phase: "idle" };
const agenda: SpatialState = { ...room, mode: "agenda" };
const service: SpatialState = { ...room, mode: "service" };

describe("spatial director", () => {
  it("keeps the camera and lens continuous when a second route interrupts a warp", () => {
    const director = createDirector(room);
    const start = director.advance(0, "high");
    director.setState(agenda);
    const departure = director.advance(0.36, "high");
    expect(departure.frame.warp).toBeGreaterThan(0.65);
    expect(departure.pose.distance).toBeLessThan(start.pose.distance);

    director.setState(service);
    const interruption = director.advance(0, "high");
    expect(interruption.pose).toEqual(departure.pose);
    expect(interruption.frame.warp).toBeCloseTo(departure.frame.warp);
    expect(interruption.frame.dissolve).toBeCloseTo(departure.frame.dissolve);

    const arrival = director.advance(1.5, "high");
    expect(arrival.frame.state.mode).toBe("service");
    expect(arrival.frame.morph).toBe(1);
    expect(arrival.frame.warp).toBe(0);
  });

  it("settles state changes immediately and freezes simulation time in reduced motion", () => {
    const director = createDirector(room);
    director.advance(0.2, "high");
    director.setState(agenda);
    director.advance(0.2, "high");
    director.setMotion(false);
    director.setState(service);
    const first = director.advance(0.4, "low");
    const later = director.advance(2, "low");
    expect(first.frame.state.mode).toBe("service");
    expect(first.frame.motion).toBe(false);
    expect(first.frame.morph).toBe(1);
    expect(first.frame.warp).toBe(0);
    expect(later).toEqual(first);
  });

  it("responds to explicit orbit input without adding inertia in reduced motion", () => {
    const director = createDirector(room);
    director.setMotion(false);
    const start = director.advance(0, "low");
    director.orbit(28, 0);
    const moved = director.advance(0, "low");
    expect(moved.pose.yaw).toBeLessThan(start.pose.yaw);
    expect(director.advance(2, "low")).toEqual(moved);
  });

  it("acknowledges a phase change once and lets its pulse settle through equivalent updates", () => {
    const director = createDirector(room);
    const voting: SpatialState = { ...room, phase: "vote", signal: 6 };
    director.setState(voting);
    const onset = director.advance(0.1, "medium").frame;
    expect(onset.pulse).toBeGreaterThan(0.5);
    expect(onset.warp).toBe(0);

    director.setState({ ...voting, level: 0.2 });
    const settled = director.advance(1, "medium").frame;
    expect(settled.pulse).toBe(0);
    expect(settled.state.level).toBe(0.2);
  });

  it("only schedules a new frame for a visual change in reduced motion", () => {
    const initial: SpatialState = { ...room, seats: [{ id: 2, status: "ready" }] };
    const director = createDirector(initial);
    director.setMotion(false);

    expect(director.setState({ ...initial, seats: [{ id: 2, status: "ready" }] })).toBe(false);
    expect(director.setState({ ...initial, level: 0.5 })).toBe(true);
    expect(director.setState({ ...initial, level: 0.5, selectedSeat: 2 })).toBe(true);
  });
});
