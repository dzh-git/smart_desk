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
  it("renders a nine-seat meeting table, a presentation screen and a device-to-screen relay", () => {
    const scene = new Scene();
    const world = createWorld(scene);
    world.update(frame({ mode: "room", phase: "live" }));
    const table = scene.getObjectByName("Conference table");
    expect(table).toBeDefined();
    expect(table?.children.filter((child) => child.name.startsWith("Conference chair "))).toHaveLength(9);

    world.update(frame({ mode: "display", phase: "live" }));
    expect(scene.getObjectByName("Meeting presentation screen")).toBeDefined();
    expect(scene.getObjectByName("SmartDesk room form")?.visible).toBe(false);

    world.update(frame({ mode: "relay", phase: "idle" }));
    expect(scene.getObjectByName("Share source")).toBeDefined();
    expect(scene.getObjectByName("Share destination")).toBeDefined();
    world.dispose();
  });

  it("sizes the visible voting columns from the supplied ballot distribution", () => {
    const scene = new Scene();
    const world = createWorld(scene);
    world.update(frame({ mode: "vote", phase: "vote", voteShares: [0.75, 0.25, 0] }));

    const first = scene.getObjectByName("Vote option 1");
    const second = scene.getObjectByName("Vote option 2");
    const third = scene.getObjectByName("Vote option 3");
    expect(first?.scale.y).toBeGreaterThan(second?.scale.y ?? Infinity);
    expect(second?.scale.y).toBeGreaterThan(third?.scale.y ?? Infinity);
    expect(scene.getObjectByName("Vote option 4")?.visible).toBe(false);
    world.dispose();
  });

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
