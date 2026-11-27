import { MODE_THEME, SEAT_HEIGHT, SEAT_RADIUS, seatAngle } from "./sceneState";
import type { SceneMode } from "./sceneState";

const TAU = Math.PI * 2;
const modes = Object.keys(MODE_THEME) as SceneMode[];
const faceYaw = 0.25;
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
      const spoke = seatAngle(lane % 9 + 1);
      const route = spoke + (v - 0.5) * 0.19;
      const radius = lane < 9 ? 1.08 + u * 1.16 : 2 + grit * 0.23;
      const bearing = lane < 9 ? route : angle;
      x = Math.cos(bearing) * radius;
      y = -0.58 + Math.sin(u * Math.PI) * 0.15 + grit * 0.15;
      z = Math.sin(bearing) * radius;
      break;
    }
    case "agenda":
    case "vote":
    case "captions": {
      const caption = mode === "captions";
      const width = mode === "vote" ? 1.67 : 1.52;
      const height = caption ? 0.32 : 0.91;
      const [horizontal, vertical] = outline(lane, u, width, height, grit);
      const depth = 0.14 + (v - 0.5) * 0.24;
      x = horizontal * faceCos + depth * faceSin;
      y = vertical + (caption ? (lane < 6 ? 0.41 : -0.37) : 0.11);
      z = depth * faceCos - horizontal * faceSin;
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
    case "station":
    case "display": {
      const isScreen = mode === "display";
      const [horizontal, vertical] = outline(lane, u, isScreen ? 1.94 : 1.30, isScreen ? 1.02 : 0.73, grit);
      const depth = (v - 0.5) * 0.26;
      x = horizontal * faceCos + depth * faceSin;
      y = vertical + 0.17;
      z = depth * faceCos - horizontal * faceSin;
      break;
    }
    case "relay": {
      x = -1.20 + u * 2.43;
      y = 0.41 + Math.sin(u * Math.PI) * 0.68 + grit * 0.17;
      z = 0.43 - u * 0.54 + (v - 0.5) * 0.26;
      break;
    }
    case "identity": {
      const [horizontal, vertical] = outline(lane, u, 0.63, 0.69, grit);
      const depth = 0.16 + (v - 0.5) * 0.20;
      x = horizontal * faceCos + depth * faceSin;
      y = vertical + 0.13;
      z = depth * faceCos - horizontal * faceSin;
      break;
    }
  }
  positions[offset] = x;
  positions[offset + 1] = y;
  positions[offset + 2] = z;
}

function outline(lane: number, offset: number, halfWidth: number, halfHeight: number, grit: number) {
  const side = lane % 4;
  const sign = side < 2 ? 1 : -1;
  const distance = offset * 2 - 1;
  if (side % 2 === 0) return [distance * halfWidth, sign * (halfHeight + grit * 0.16)] as const;
  return [sign * (halfWidth + grit * 0.16), distance * halfHeight] as const;
}
