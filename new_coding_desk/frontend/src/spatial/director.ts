import { getSceneChange, type RenderQuality, type SceneMode, type SpatialFrame, type SpatialState } from "./sceneState";

interface CameraPose {
  yaw: number;
  elevation: number;
  distance: number;
  targetY: number;
  roll: number;
}

const MODE_POSE: Record<SceneMode, CameraPose> = {
  room: { yaw: 0.53, elevation: 0.4, distance: 7, targetY: -0.27, roll: -0.018 },
  agenda: { yaw: 0.31, elevation: 0.34, distance: 6.8, targetY: -0.23, roll: 0.025 },
  service: { yaw: 0.69, elevation: 0.44, distance: 7.2, targetY: -0.25, roll: -0.026 },
  station: { yaw: 0.48, elevation: 0.35, distance: 6.9, targetY: -0.24, roll: -0.015 },
  display: { yaw: 0.38, elevation: 0.31, distance: 7.1, targetY: -0.18, roll: 0.019 },
  relay: { yaw: 0.63, elevation: 0.38, distance: 7.3, targetY: -0.22, roll: -0.017 },
  identity: { yaw: 0.42, elevation: 0.37, distance: 7, targetY: -0.25, roll: 0.02 },
};

const WARP_DURATION = 1.14;
const PULSE_DURATION = 0.66;
const DISSOLVE_DURATION = 0.91;

function clamp(value: number, min = 0, max = 1) {
  return Math.min(max, Math.max(min, value));
}

function mix(a: number, b: number, t: number) {
  return a + (b - a) * t;
}

function smooth(from: number, to: number, value: number) {
  const t = clamp((value - from) / (to - from));
  return t * t * (3 - 2 * t);
}

function envelope(t: number, peak: number, tail: number) {
  return smooth(0, peak, t) * (1 - smooth(tail, 1, t));
}

interface RouteTransition {
  from: CameraPose;
  age: number;
  direction: number;
  inheritedWarp: number;
  inheritedDissolve: number;
}

export function createDirector(initialState: SpatialState) {
  let state = initialState;
  let previousMode = state.mode;
  let pose = MODE_POSE[state.mode];
  let route: RouteTransition | null = null;
  let motion = true;
  let time = 0;
  let morph = 1;
  let warp = 0;
  let routeDissolve = 0;
  let pulseAge = PULSE_DURATION;
  let dissolveAge = DISSOLVE_DURATION;
  let pointerX = 0;
  let pointerY = 0;
  let targetPointerX = 0;
  let targetPointerY = 0;
  let orbitYaw = 0;
  let orbitPitch = 0;
  let targetOrbitYaw = 0;
  let targetOrbitPitch = 0;

  function settle() {
    pose = MODE_POSE[state.mode];
    previousMode = state.mode;
    route = null;
    morph = 1;
    warp = 0;
    routeDissolve = 0;
    pulseAge = PULSE_DURATION;
    dissolveAge = DISSOLVE_DURATION;
  }

  return {
    setState(next: SpatialState) {
      const change = getSceneChange(state, next);
      if (motion && change === "warp") {
        if (morph >= 0.5) previousMode = state.mode;
        route = {
          from: pose,
          age: 0,
          direction: MODE_POSE[next.mode].yaw < pose.yaw ? -1 : 1,
          inheritedWarp: warp,
          inheritedDissolve: routeDissolve,
        };
        morph = 0;
      }
      if (motion && change === "burst") pulseAge = 0;
      if (motion && change === "dissolve") dissolveAge = 0;
      state = next;
      if (!motion) settle();
    },
    setMotion(next: boolean) {
      motion = next;
      if (!motion) {
        settle();
        pointerX = 0;
        pointerY = 0;
        targetPointerX = 0;
        targetPointerY = 0;
        targetOrbitYaw = orbitYaw;
        targetOrbitPitch = orbitPitch;
      }
    },
    movePointer(x: number, y: number) {
      targetPointerX = clamp(x, -1, 1);
      targetPointerY = clamp(y, -1, 1);
    },
    orbit(dx: number, dy: number) {
      targetOrbitYaw -= dx * 0.004;
      targetOrbitPitch = clamp(targetOrbitPitch + dy * 0.003, -0.28, 0.34);
      if (!motion) {
        orbitYaw = targetOrbitYaw;
        orbitPitch = targetOrbitPitch;
      }
    },
    advance(dt: number, quality: RenderQuality) {
      const elapsed = motion ? dt : 0;
      time += elapsed;
      pulseAge = Math.min(pulseAge + elapsed, PULSE_DURATION);
      dissolveAge = Math.min(dissolveAge + elapsed, DISSOLVE_DURATION);
      const damping = 1 - Math.exp(-9 * elapsed);
      pointerX = mix(pointerX, targetPointerX, damping);
      pointerY = mix(pointerY, targetPointerY, damping);
      orbitYaw = mix(orbitYaw, targetOrbitYaw, damping);
      orbitPitch = mix(orbitPitch, targetOrbitPitch, damping);

      if (route) {
        route.age += elapsed;
        const t = clamp(route.age / WARP_DURATION);
        const surge = envelope(t, 0.34, 0.43);
        const influence = 1 - smooth(0, 0.52, t);
        warp = mix(surge, 1, route.inheritedWarp * influence);
        routeDissolve = mix(envelope(t, 0.46, 0.55) * 0.8, 1, route.inheritedDissolve * influence);
        morph = smooth(0.17, 0.93, t);
        const destination = MODE_POSE[state.mode];
        const travel = smooth(0, 1, t);
        const distance = mix(route.from.distance, destination.distance, travel);
        pose = {
          yaw: mix(route.from.yaw, destination.yaw, travel) + route.direction * surge * 0.34,
          elevation: mix(route.from.elevation, destination.elevation, travel) - surge * 0.115,
          distance: Math.max(4.55, distance - surge * 2.2),
          targetY: mix(route.from.targetY, destination.targetY, travel) + surge * 0.12,
          roll: mix(route.from.roll, destination.roll, travel) - route.direction * surge * 0.15,
        };
        if (t === 1) {
          route = null;
          previousMode = state.mode;
        }
      }

      const frame: SpatialFrame = {
        state, previousMode, morph, time, dt: elapsed, motion, quality, warp, pointerX, pointerY,
        pulse: Math.max(warp * 0.6, envelope(pulseAge / PULSE_DURATION, 0.12, 0.17)),
        dissolve: Math.max(routeDissolve, envelope(dissolveAge / DISSOLVE_DURATION, 0.21, 0.27) * 0.85),
      };
      return {
        frame,
        pose: {
          yaw: pose.yaw + orbitYaw + pointerX * 0.09 + (motion ? Math.sin(time * 0.34) * 0.045 : 0),
          elevation: pose.elevation + orbitPitch + pointerY * 0.065 + (motion ? Math.sin(time * 0.26) * 0.023 : 0),
          distance: pose.distance + (motion ? Math.sin(time * 0.38) * 0.14 : 0),
          targetY: pose.targetY,
          roll: pose.roll + pointerX * 0.018 + (motion ? Math.sin(time * 0.24) * 0.017 : 0),
        },
      };
    },
  };
}
