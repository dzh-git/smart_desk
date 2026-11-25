import { Object3D, Scene } from "three";
import { describe, expect, it } from "vitest";
import type { SpatialFrame, SpatialState } from "../sceneState";
import { createWorld } from "../world";

function frame(state: SpatialState): SpatialFrame {
  return {
    state, previousMode: state.mode, morph: 1, time: 0, dt: 0,
    pulse: 0, warp: 0, dissolve: 0, pointerX: 0, pointerY: 0,
    motion: false, quality: "high",
  };
}

describe("SmartDesk spatial world", () => {
  it("keeps projected seats aligned with the supplied meeting seats", () => {
    const world = createWorld(new Scene());

    world.update(frame({ mode: "room", phase: "idle" }));
    expect(world.seatAnchors.size).toBe(0);

    world.update(frame({ mode: "room", phase: "live", seats: [
      { id: 1, status: "speaking" }, { id: 5, status: "vacant" },
    ] }));
    const leader = world.seatAnchors.get(1);
    expect([...world.seatAnchors.keys()]).toEqual([1, 5]);
    expect(leader?.position.z).toBeCloseTo(2.13);
    expect(leader?.position.y).toBeCloseTo(-0.54);

    world.update(frame({ mode: "room", phase: "live", seats: [{ id: 1, status: "ready" }] }));
    expect(world.seatAnchors.get(1)).toBe(leader);
    expect(world.seatAnchors.has(5)).toBe(false);

    world.dispose();
  });

  it("detaches the world without removing another scene owner's objects", () => {
    const scene = new Scene();
    const otherOwner = new Object3D();
    scene.add(otherOwner);
    const world = createWorld(scene);
    world.update(frame({ mode: "room", phase: "live", seats: [{ id: 1, status: "ready" }] }));

    world.dispose();

    expect(scene.children).toEqual([otherOwner]);
    expect(world.seatAnchors.size).toBe(0);
  });

  it("retargets an interrupted transition from the sculpture's visible pose", () => {
    const scene = new Scene();
    const world = createWorld(scene);
    const room = frame({ mode: "room", phase: "live" });
    world.update(room);
    const sculpture = scene.getObjectByName("SmartDesk room form")!;

    world.update({ ...frame({ mode: "agenda", phase: "idle" }), previousMode: "room", morph: 0.42, motion: true });
    const previousScale = sculpture.scale.x;
    const previousPosition = sculpture.position.clone();

    world.update({ ...room, morph: 0, motion: true });

    expect(sculpture.visible).toBe(true);
    expect(sculpture.scale.x).toBeCloseTo(previousScale);
    expect(sculpture.position.distanceTo(previousPosition)).toBeCloseTo(0);
    world.dispose();
  });
});
