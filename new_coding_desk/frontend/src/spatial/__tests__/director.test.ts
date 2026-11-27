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

  it("trucks and pans horizontally while the lens opens on a route push-in", () => {
    const director = createDirector(room);
    const start = director.advance(0, "high").pose;
    director.setState(agenda);
    const travel = director.advance(0.36, "high").pose;
    expect(Math.abs(travel.truck - start.truck)).toBeGreaterThan(0.9);
    expect(Math.abs(travel.pan - start.pan)).toBeGreaterThan(0.32);
    expect(travel.distance).toBeLessThan(start.distance - 1);
    expect(travel.focal).toBeLessThan(start.focal);

    const settled = director.advance(0.8, "high");
    expect(Math.abs(settled.pose.truck)).toBeLessThan(0.2);
    expect(Math.abs(settled.pose.pan)).toBeLessThan(0.2);
    expect(settled.frame.warp).toBe(0);
  });

  it("acknowledges a tap with a bounded dolly and aimed pan without starting a route warp", () => {
    const director = createDirector(room);
    const resting = createDirector(room);
    expect(director.impulse(1, 0)).toBe(true);
    const active = director.advance(0.15, "high");
    const idle = resting.advance(0.15, "high");
    expect(active.pose.distance).toBeLessThan(idle.pose.distance - 0.3);
    expect(active.pose.distance).toBeGreaterThan(idle.pose.distance - 0.7);
    expect(active.pose.pan).toBeGreaterThan(idle.pose.pan + 0.08);
    expect(active.frame.pulse).toBeGreaterThan(0.5);
    expect(active.frame.warp).toBe(0);

    director.impulse(-1, 0);
    expect(director.advance(0, "high").pose).toEqual(active.pose);
    expect(director.advance(0.9, "high").pose).toEqual(resting.advance(0.9, "high").pose);
  });

  it("pushes toward a selected seat and respects reduced motion for taps and selection", () => {
    const state: SpatialState = { ...room, seats: [{ id: 2, status: "ready" }] };
    const director = createDirector(state);
    const initial = director.advance(0, "low");
    director.setState({ ...state, selectedSeat: 2 });
    expect(director.advance(0.15, "low").pose.distance).toBeLessThan(initial.pose.distance - 0.3);

    director.setMotion(false);
    const resting = director.advance(0, "low");
    expect(director.impulse(1, 1)).toBe(false);
    director.setState({ ...state, selectedSeat: null, signal: 2 });
    const later = director.advance(0.15, "low");
    expect(later.pose).toEqual(resting.pose);
    expect(later.frame.pulse).toBe(0);
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
