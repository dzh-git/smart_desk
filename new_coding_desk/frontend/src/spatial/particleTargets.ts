import { MODE_THEME, SEAT_HEIGHT, SEAT_RADIUS, seatAngle } from "./sceneState";
import type { SceneMode } from "./sceneState";

const TAU = Math.PI * 2;
const modes = Object.keys(MODE_THEME) as SceneMode[];
const faceYaw = 0.48;
const faceCos = Math.cos(faceYaw);
const faceSin = Math.sin(faceYaw);

export function createParticleTargets(count: number) {
  const targets = Object.fromEntries(modes.map((mode) => [mode, new Float32Array(count * 3)])) as Record<SceneMode, Float32Array>;
  const seeds = new Float32Array(count);
  const drift = new Float32Array(count);
  const lifetimes = new Float32Array(count);
  const ages = new Float32Array(count);
  let randomState = 0xc0deb31d;

  function random() {
    randomState = (Math.imul(randomState, 1664525) + 1013904223) >>> 0;
    return randomState / 4294967296;
  }

  for (let i = 0; i < count; i++) {
    const offset = i * 3;
    const angle = random() * TAU;
    const u = random();
    const v = random();
    const grit = random() - 0.5;
    const lane = Math.floor(random() * 36);
    const layer = lane % 12;
    seeds[i] = random();
    const driftChance = 0.16 - 0.126 * Math.sqrt(i / count);
    drift[i] = random() < driftChance ? 1 : 0;
    lifetimes[i] = 6 + random() * 9;
    ages[i] = 0.35 + random() * (lifetimes[i] - 0.9);

    for (const mode of modes) {
      if (drift[i]) {
        const radius = 2.14 + u * 0.66;
        targets[mode][offset] = Math.cos(angle) * radius;
        targets[mode][offset + 1] = (v - 0.5) * 2.16;
        targets[mode][offset + 2] = Math.sin(angle) * radius;
      } else {
        placeTarget(targets[mode], offset, mode, angle, u, v, grit, mode === "service" ? lane % 9 : layer);
      }
    }
  }

  return { targets, seeds, drift, ages, lifetimes };
}

function placeTarget(
  positions: Float32Array,
  offset: number,
  mode: SceneMode,
  angle: number,
  u: number,
  v: number,
  grit: number,
  lane: number,
) {
  let x: number;
  let y: number;
  let z: number;
  switch (mode) {
    case "room": {
      // A faceted shell threaded by a few narrow lower orbits.
      if (lane < 3) {
        const radius = 1.66 + lane * 0.12 + grit * 0.12;
        x = Math.cos(angle) * radius;
        y = -0.48 + Math.sin(angle * 2 + lane) * (0.09 + lane * 0.05) + (v - 0.5) * 0.12;
        z = Math.sin(angle) * radius;
      } else {
        y = (u - 0.5) * 1.96;
        const radius = Math.sqrt(Math.max(0, 1 - y * y));
        const edgeAngle = angle + Math.sin(angle * 6) * 0.075;
        x = Math.cos(edgeAngle) * radius;
        z = Math.sin(edgeAngle) * radius;
        const faceRadius = 1.71 / Math.pow(Math.abs(x) ** 1.45 + Math.abs(y) ** 1.45 + Math.abs(z) ** 1.45, 1 / 1.45);
        const scale = faceRadius + grit * 0.15;
        x *= scale;
        y *= scale;
        z *= scale;
      }
      break;
    }
    case "agenda": {
      const ring = lane % 4;
      const radius = 1.24 + ring * 0.26 + grit * 0.13;
      const arc = (lane / 12) * TAU + angle * (0.63 + ring * 0.08);
      x = Math.cos(arc) * radius;
      y = (ring - 1.5) * 0.30 + Math.sin(arc + ring * 0.8) * (0.34 + 0.07 * ring) + (u - 0.5) * 0.11;
      z = Math.sin(arc) * radius;
      break;
    }
    case "service": {
      const spoke = seatAngle(lane + 1);
      const route = spoke + Math.sin(u * Math.PI) * (lane % 2 ? 0.18 : -0.18) + grit * 0.06;
      const radius = 0.63 + u * (SEAT_RADIUS - 0.60);
      x = Math.cos(route) * radius;
      y = SEAT_HEIGHT * u + Math.sin(u * Math.PI) * 0.48 + (v - 0.5) * 0.16;
      z = Math.sin(route) * radius;
      break;
    }
    case "station": {
      const edge = lane % 6;
      const edgeAngle = edge * TAU / 6;
      const nextAngle = edgeAngle + TAU / 6;
      y = (u - 0.5) * 3.17;
      const radius = 1.62 * (1 - Math.abs(y) / 1.86) + grit * 0.11;
      x = (Math.cos(edgeAngle) * (1 - v) + Math.cos(nextAngle) * v) * radius;
      z = (Math.sin(edgeAngle) * (1 - v) + Math.sin(nextAngle) * v) * radius;
      break;
    }
    case "display": {
      const ring = lane % 3;
      const radius = 1.44 + ring * 0.18 + grit * 0.10;
      const horizontal = Math.cos(angle) * radius;
      const depth = (ring - 1) * 0.21 + (v - 0.5) * 0.13;
      x = horizontal * faceCos + depth * faceSin;
      y = Math.sin(angle) * radius * (0.92 + ring * 0.03) + (ring - 1) * 0.09;
      z = depth * faceCos - horizontal * faceSin;
      break;
    }
    case "relay": {
      const ring = lane % 4;
      const radius = 1.30 + ring * 0.19 + grit * 0.08;
      const arc = lane * TAU / 12 + angle * (0.60 + 0.05 * ring);
      const horizontal = Math.cos(arc) * radius;
      const depth = (ring - 1.5) * 0.34 + Math.sin(arc) * 0.52 + grit * 0.16;
      x = horizontal * faceCos + depth * faceSin;
      y = Math.sin(arc) * radius * 0.72 + (ring - 1.5) * 0.15;
      z = depth * faceCos - horizontal * faceSin;
      break;
    }
    case "identity": {
      const side = lane < 6 ? -1 : 1;
      const edgeAngle = (lane % 3) * TAU / 3 + side * 0.4;
      const nextAngle = edgeAngle + TAU / 3;
      const radius = 0.62 + grit * 0.18;
      y = (u - 0.5) * 2.83 + side * 0.17;
      const horizontal = side * 0.69 + y * side * 0.21
        + (Math.cos(edgeAngle) * (1 - v) + Math.cos(nextAngle) * v) * radius;
      const depth = side * 0.28
        + (Math.sin(edgeAngle) * (1 - v) + Math.sin(nextAngle) * v) * radius;
      x = horizontal * faceCos + depth * faceSin;
      z = depth * faceCos - horizontal * faceSin;
      break;
    }
  }
  positions[offset] = x;
  positions[offset + 1] = y;
  positions[offset + 2] = z;
}
