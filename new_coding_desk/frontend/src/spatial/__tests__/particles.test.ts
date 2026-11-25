import { describe, expect, it } from "vitest";
import { BufferAttribute, Points, Scene } from "three";
import { createParticles } from "../particles";
import type { SpatialFrame } from "../sceneState";

const frame: SpatialFrame = {
  state: { mode: "room", phase: "idle" },
  previousMode: "room",
  morph: 1,
  time: 0,
  dt: 1 / 60,
  pulse: 0,
  warp: 0,
  dissolve: 0,
  pointerX: 0,
  pointerY: 0,
  motion: true,
  quality: "high",
};

function fieldPoints(scene: Scene): Points {
  let result: Points | undefined;
  scene.traverse((child) => {
    if (child instanceof Points) result = child;
  });
  if (!result) throw new Error("The particle field did not add a point cloud");
  return result;
}

function meanRadius(positions: Float32Array, count: number) {
  let radius = 0;
  for (let i = 0; i < count * 3; i += 3) {
    radius += Math.hypot(positions[i], positions[i + 1], positions[i + 2]);
  }
  return radius / count;
}

describe("spatial particles", () => {
  it("adapts the drawn count in place and detaches when disposed", () => {
    const scene = new Scene();
    const field = createParticles(scene);
    field.update(frame);
    const points = fieldPoints(scene);
    const highCount = points.geometry.drawRange.count;
    expect(highCount).toBeGreaterThanOrEqual(1200);
    const positions = points.geometry.getAttribute("position").array;

    field.update({ ...frame, quality: "medium" });
    const mediumCount = points.geometry.drawRange.count;
    expect(mediumCount).toBeLessThan(highCount);
    field.update({ ...frame, quality: "low" });
    expect(points.geometry.drawRange.count).toBeLessThan(mediumCount);
    expect(points.geometry.drawRange.count).toBeGreaterThan(0);
    expect(points.geometry.getAttribute("position").array).toBe(positions);

    field.dispose();
    expect(scene.children).toHaveLength(0);
  });

  it("compresses during a warp before reconstructing into the new target", () => {
    const scene = new Scene();
    const field = createParticles(scene);
    field.update(frame);
    const points = fieldPoints(scene);
    const positions = (points.geometry.getAttribute("position") as BufferAttribute).array as Float32Array;
    const count = points.geometry.drawRange.count;
    const startingRadius = meanRadius(positions, count);
    const agenda = { mode: "agenda", phase: "live" } as const;

    for (let i = 1; i <= 45; i++) {
      field.update({ ...frame, state: agenda, time: i / 60, morph: 0.5, warp: 1 });
    }
    expect(meanRadius(positions, count)).toBeLessThan(startingRadius * 0.68);
    for (let i = 46; i <= 110; i++) {
      field.update({ ...frame, state: agenda, time: i / 60 });
    }
    expect(meanRadius(positions, count)).toBeGreaterThan(startingRadius * 0.72);
    field.dispose();
  });

  it("scatters and fades a cloud during a dissolve", () => {
    const scene = new Scene();
    const field = createParticles(scene);
    field.update(frame);
    const points = fieldPoints(scene);
    const positions = points.geometry.getAttribute("position").array as Float32Array;
    const energy = points.geometry.getAttribute("aEnergy").array as Float32Array;
    const count = points.geometry.drawRange.count;
    const startingRadius = meanRadius(positions, count);
    const startingEnergy = energy.reduce((sum, value) => sum + value, 0);

    for (let i = 1; i <= 45; i++) {
      field.update({ ...frame, time: i / 60, dissolve: 1 });
    }
    expect(meanRadius(positions, count)).toBeGreaterThan(startingRadius * 1.25);
    expect(energy.reduce((sum, value) => sum + value, 0)).toBeLessThan(startingEnergy * 0.24);
    field.dispose();
  });

  it("settles immediately into the chosen mode with reduced motion", () => {
    const scene = new Scene();
    const field = createParticles(scene);
    field.update({ ...frame, motion: false });
    const points = fieldPoints(scene);
    const positions = points.geometry.getAttribute("position").array;
    const roomPositions = positions.slice();

    const state = { mode: "identity", phase: "idle" } as const;
    field.update({ ...frame, state, motion: false, morph: 0.1, time: 3, warp: 0.9, pulse: 1 });
    const identityPositions = positions.slice();
    expect(identityPositions).not.toEqual(roomPositions);

    field.update({ ...frame, state, motion: false, time: 5, dissolve: 1, pointerX: 0.9 });
    expect(positions).toEqual(identityPositions);
    field.dispose();
  });
});
