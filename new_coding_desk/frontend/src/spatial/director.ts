import { getSceneChange, type RenderQuality, type SceneMode, type SpatialFrame, type SpatialState } from "./sceneState";

interface CameraPose {
  yaw: number;
  elevation: number;
  distance: number;
  targetY: number;
  roll: number;
  /** Camera and aim offsets along the current camera's right axis. */
  truck: number;
  pan: number;
  /** Lens multiplier and minimum half-width of the subject in world units. */
  focal: number;
  frameWidth: number;
}

const MODE_POSE: Record<SceneMode, Omit<CameraPose, "truck">> = {
  room: { yaw: 0.55, elevation: 0.48, distance: 6.65, targetY: -0.39, roll: -0.009, pan: 0.04, focal: 1.09, frameWidth: 2.76 },
  agenda: { yaw: 0.22, elevation: 0.31, distance: 6.35, targetY: -0.13, roll: 0.018, pan: -0.08, focal: 1.04, frameWidth: 2.12 },
  vote: { yaw: 0.43, elevation: 0.37, distance: 6.35, targetY: -0.19, roll: -0.012, pan: 0.07, focal: 1.10, frameWidth: 2.12 },
  captions: { yaw: 0.12, elevation: 0.26, distance: 6.2, targetY: -0.06, roll: 0.01, pan: -0.04, focal: 1.12, frameWidth: 2.1 },
  service: { yaw: 0.74, elevation: 0.42, distance: 6.62, targetY: -0.18, roll: -0.018, pan: 0.10, focal: 1.05, frameWidth: 2.12 },
  station: { yaw: 0.48, elevation: 0.35, distance: 6.65, targetY: -0.24, roll: -0.015, pan: 0.05, focal: 1.03, frameWidth: 2.16 },
  display: { yaw: 0.36, elevation: 0.3, distance: 6.72, targetY: -0.16, roll: 0.012, pan: -0.06, focal: 1.05, frameWidth: 2.16 },
  relay: { yaw: 0.58, elevation: 0.34, distance: 6.7, targetY: -0.18, roll: -0.016, pan: 0.04, focal: 1.06, frameWidth: 2.22 },
  identity: { yaw: 0.33, elevation: 0.32, distance: 6.58, targetY: -0.2, roll: 0.018, pan: -0.04, focal: 1.06, frameWidth: 2.1 },
};

const WARP_DURATION = 1.08;
const ACTION_DURATION = 0.72;
const MAX_PUSH = 0.62;
const MIN_DISTANCE = 4.85;
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

const RESTING_ACTION = { push: 0, pan: 0, lift: 0 };

export function createDirector(initialState: SpatialState) {
  let state = initialState;
  let previousMode = state.mode;
  let pose: CameraPose = { ...MODE_POSE[state.mode], truck: 0 };
  let route: RouteTransition | null = null;
  let action: { age: number; x: number; y: number; from: typeof RESTING_ACTION } | null = null;
  let actionPose = RESTING_ACTION;
  let motion = true;
  let time = 0;
  let morph = 1;
  let warp = 0;
  let routeDissolve = 0;
  let pulse = 0;
  let inheritedPulse = 0;
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

  function cuePulse() {
    inheritedPulse = pulse;
    pulseAge = 0;
  }

  function impulse(x = 0, y = 0) {
    if (!motion) return false;
    action = { age: 0, x: clamp(x, -1, 1), y: clamp(y, -1, 1), from: actionPose };
    cuePulse();
    return true;
  }

  function settle() {
    pose = { ...MODE_POSE[state.mode], truck: 0 };
    previousMode = state.mode;
    route = null;
    action = null;
    actionPose = RESTING_ACTION;
    morph = 1;
    warp = 0;
    routeDissolve = 0;
    pulse = 0;
    inheritedPulse = 0;
    pulseAge = PULSE_DURATION;
    dissolveAge = DISSOLVE_DURATION;
  }

  return {
    setState(next: SpatialState) {
      const change = getSceneChange(state, next);
      if (change === "none" && (state.level ?? 0) === (next.level ?? 0)) return false;
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
      if (motion && change === "burst") {
        const actionChanged = state.phase !== next.phase || state.signal !== next.signal
          || (state.selectedSeat !== next.selectedSeat && next.selectedSeat != null);
        if (actionChanged && action?.age !== 0) impulse();
        else cuePulse();
      }
      if (motion && change === "dissolve") dissolveAge = 0;
      state = next;
      if (!motion) settle();
      return true;
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
    impulse,
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
        const surge = envelope(t, 0.31, 0.42);
        const influence = 1 - smooth(0, 0.52, t);
        warp = mix(surge, 1, route.inheritedWarp * influence);
        routeDissolve = mix(envelope(t, 0.46, 0.55) * 0.8, 1, route.inheritedDissolve * influence);
        morph = smooth(0.17, 0.93, t);
        const destination = MODE_POSE[state.mode];
        const travel = smooth(0, 1, t);
        const distance = mix(route.from.distance, destination.distance, travel);
        const returnSweep = smooth(0.52, 0.72, t) * (1 - smooth(0.79, 1, t));
        const sweep = route.direction * (surge - returnSweep * 0.30);
        pose = {
          yaw: mix(route.from.yaw, destination.yaw, travel) + sweep * 0.26,
          elevation: mix(route.from.elevation, destination.elevation, travel) - surge * 0.09,
          distance: Math.max(MIN_DISTANCE, distance - surge * 1.78),
          targetY: mix(route.from.targetY, destination.targetY, travel) + surge * 0.13,
          roll: mix(route.from.roll, destination.roll, travel) - sweep * 0.105,
          truck: clamp(mix(route.from.truck, 0, travel) + sweep * 1.16, -1.4, 1.4),
          pan: clamp(mix(route.from.pan, destination.pan, travel) + sweep * 0.42, -0.56, 0.56),
          focal: Math.max(0.84, mix(route.from.focal, destination.focal, travel) - surge * 0.15),
          frameWidth: mix(route.from.frameWidth, destination.frameWidth, travel),
        };
        if (t === 1) {
          route = null;
          previousMode = state.mode;
        }
      }

      if (action) {
        action.age += elapsed;
        const t = clamp(action.age / ACTION_DURATION);
        const attack = envelope(t, 0.17, 0.28);
        const carry = 1 - smooth(0, 0.55, t);
        actionPose = {
          push: mix(attack * 0.51, MAX_PUSH, action.from.push / MAX_PUSH * carry),
          pan: clamp(action.from.pan * carry + action.x * attack * 0.145, -0.19, 0.19),
          lift: clamp(action.from.lift * carry + action.y * attack * 0.095, -0.12, 0.12),
        };
        if (t === 1) action = null;
      }

      const pulseTime = pulseAge / PULSE_DURATION;
      pulse = mix(envelope(pulseTime, 0.12, 0.17), 1, inheritedPulse * (1 - smooth(0, 0.44, pulseTime)));
      const frame: SpatialFrame = {
        state, previousMode, morph, time, dt: elapsed, motion, quality, warp, pointerX, pointerY,
        pulse: Math.max(warp * 0.6, pulse),
        dissolve: Math.max(routeDissolve, envelope(dissolveAge / DISSOLVE_DURATION, 0.21, 0.27) * 0.85),
      };
      return {
        frame,
        pose: {
          ...pose,
          yaw: pose.yaw + orbitYaw + pointerX * 0.09 + (motion ? Math.sin(time * 0.34) * 0.045 : 0),
          elevation: pose.elevation + orbitPitch + pointerY * 0.065 + (motion ? Math.sin(time * 0.26) * 0.023 : 0),
          distance: Math.max(MIN_DISTANCE, pose.distance - actionPose.push + (motion ? Math.sin(time * 0.38) * 0.14 : 0)),
          targetY: pose.targetY + actionPose.lift,
          roll: pose.roll + pointerX * 0.018 + (motion ? Math.sin(time * 0.24) * 0.017 : 0),
          truck: pose.truck + actionPose.pan * 0.55,
          pan: pose.pan + actionPose.pan,
          focal: pose.focal + actionPose.push * 0.066,
        },
      };
    },
  };
}
