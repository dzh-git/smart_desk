import { BufferAttribute, BufferGeometry, Color, DynamicDrawUsage, LineSegments, Matrix4, Points, Vector3 } from "three";
import type { Scene } from "three";
import { createPointMaterial, createTrailMaterial } from "./particleMaterials";
import { createParticleTargets } from "./particleTargets";
import { getTheme } from "./sceneState";
import type { RenderQuality, SceneMode, ScenePhase, SpatialFrame } from "./sceneState";

const POINT_COUNTS: Record<RenderQuality, number> = { high: 1728, medium: 768, low: 288 };
const TRAIL_COUNTS: Record<RenderQuality, number> = { high: 276, medium: 112, low: 0 };
export function createParticles(scene: Scene): { update(frame: SpatialFrame): void; dispose(): void } {
  const { high: capacity } = POINT_COUNTS;
  const { targets, seeds, drift, ages, lifetimes } = createParticleTargets(capacity);
  const positions = new Float32Array(capacity * 3);
  const velocities = new Float32Array(capacity * 3);
  const energy = new Float32Array(capacity);
  const pointPosition = new BufferAttribute(positions, 3).setUsage(DynamicDrawUsage);
  const pointEnergy = new BufferAttribute(energy, 1).setUsage(DynamicDrawUsage);
  const pointGeometry = new BufferGeometry();
  pointGeometry.setAttribute("position", pointPosition);
  pointGeometry.setAttribute("aEnergy", pointEnergy);
  pointGeometry.setAttribute("aSeed", new BufferAttribute(seeds, 1));
  pointGeometry.setAttribute("aDrift", new BufferAttribute(drift, 1));
  pointGeometry.setDrawRange(0, 0);

  const pointMaterial = createPointMaterial();
  const points = new Points(pointGeometry, pointMaterial);
  points.name = "Orbital particle field";
  points.frustumCulled = false;
  points.renderOrder = 8;
  const pointerProjection = new Matrix4();
  const pointerPosition = new Vector3();
  const projectedOrigin = new Vector3();
  let hasCamera = false;
  points.onBeforeRender = (renderer, _scene, camera) => {
    pointMaterial.uniforms.uPixelRatio.value = renderer.getPixelRatio();
    pointerProjection.multiplyMatrices(camera.matrixWorld, camera.projectionMatrixInverse);
    projectedOrigin.set(0, 0, 0).project(camera);
    hasCamera = true;
  };

  const trailPositions = new Float32Array(TRAIL_COUNTS.high * 6);
  const trailEnergy = new Float32Array(TRAIL_COUNTS.high * 2);
  const trailSeeds = new Float32Array(TRAIL_COUNTS.high * 2);
  for (let i = 0; i < TRAIL_COUNTS.high; i++) {
    trailSeeds[i * 2] = seeds[i];
    trailSeeds[i * 2 + 1] = seeds[i];
  }
  const trailPosition = new BufferAttribute(trailPositions, 3).setUsage(DynamicDrawUsage);
  const trailBrightness = new BufferAttribute(trailEnergy, 1).setUsage(DynamicDrawUsage);
  const trailGeometry = new BufferGeometry();
  trailGeometry.setAttribute("position", trailPosition);
  trailGeometry.setAttribute("aEnergy", trailBrightness);
  trailGeometry.setAttribute("aSeed", new BufferAttribute(trailSeeds, 1));
  trailGeometry.setDrawRange(0, 0);

  const trailMaterial = createTrailMaterial();
  const trails = new LineSegments(trailGeometry, trailMaterial);
  trails.name = "Particle motion trails";
  trails.frustumCulled = false;
  trails.renderOrder = 7;
  scene.add(points, trails);

  const accent = new Color();
  const secondary = new Color();
  const targetAccent = new Color();
  const targetSecondary = new Color();
  const departingAccent = new Color();
  const departingSecondary = new Color();
  pointMaterial.uniforms.uAccent.value = trailMaterial.uniforms.uAccent.value = accent;
  pointMaterial.uniforms.uSecondary.value = trailMaterial.uniforms.uSecondary.value = secondary;

  let lastCount = 0;
  let lastMotion = true;
  let lastMode: SceneMode | undefined;
  let lastPhase: ScenePhase | undefined;
  let lastPulse = 0;

  function update(frame: SpatialFrame) {
    const { state, motion, quality } = frame;
    const count = POINT_COUNTS[quality];
    const trailCount = motion ? TRAIL_COUNTS[quality] : 0;
    const themeChanged = state.mode !== lastMode || state.phase !== lastPhase;
    if (!motion && !lastMotion && !themeChanged && count === lastCount) return;

    const dt = motion ? Math.max(0, Math.min(frame.dt, 0.042)) : 0;
    const morph = motion ? frame.morph * frame.morph * (3 - 2 * frame.morph) : 1;
    if (themeChanged) {
      const theme = getTheme(state);
      targetAccent.set(theme.accent);
      targetSecondary.set(theme.secondary);
      if (state.mode !== lastMode) {
        departingAccent.copy(accent);
        departingSecondary.copy(secondary);
      }
    }
    if (morph < 1 && lastCount > 0) {
      accent.copy(departingAccent).lerp(targetAccent, morph);
      secondary.copy(departingSecondary).lerp(targetSecondary, morph);
    } else {
      const tint = motion && lastCount > 0 ? 1 - Math.exp(-dt * 6.8) : 1;
      accent.lerp(targetAccent, tint);
      secondary.lerp(targetSecondary, tint);
    }

    const time = motion ? frame.time : 0;
    const warp = motion ? frame.warp : 0;
    const pulse = motion ? frame.pulse : 0;
    const kick = Math.max(0, pulse - lastPulse) * 2.9;
    const dissolve = motion ? frame.dissolve : 0;
    const wobble = Math.sin(time * 0.43) * 0.065 + warp * 0.82;
    const driftAngle = -time * 0.075 + warp * 1.4;
    const cos = Math.cos(wobble);
    const sin = Math.sin(wobble);
    const driftCos = Math.cos(driftAngle);
    const driftSin = Math.sin(driftAngle);
    const stiffness = 17 + warp * 32;
    const damping = Math.exp(-dt * (6.5 + warp * 2.1));
    const from = targets[frame.previousMode];
    const to = targets[state.mode];

    // Place the pointer in the camera-facing plane through the subject.
    if (hasCamera) {
      pointerPosition.set(frame.pointerX, frame.pointerY, projectedOrigin.z).applyMatrix4(pointerProjection);
    } else {
      pointerPosition.set(frame.pointerX * 2.21 - frame.pointerY * 0.40, frame.pointerY * 1.95,
        -frame.pointerX * 1.28 - frame.pointerY * 0.68);
    }
    const pointerStrength = Math.min(1, Math.hypot(frame.pointerX, frame.pointerY) * 3.5) * 5.2;
    const flowPhase = time * 0.64;
    const flowAmplitude = (0.38 + dissolve * 1.4 + pulse * 0.45) * (1 - warp * 0.62);

    for (let i = 0; i < count; i++) {
      const offset = i * 3;
      const seed = seeds[i];
      const airborne = drift[i] === 1;
      const baseX = from[offset] + (to[offset] - from[offset]) * morph;
      const baseY = from[offset + 1] + (to[offset + 1] - from[offset + 1]) * morph;
      const baseZ = from[offset + 2] + (to[offset + 2] - from[offset + 2]) * morph;
      const orbitX = airborne
        ? to[offset] * driftCos - to[offset + 2] * driftSin
        : baseX * cos - baseZ * sin;
      const orbitZ = airborne
        ? to[offset] * driftSin + to[offset + 2] * driftCos
        : baseX * sin + baseZ * cos;
      const pulseSpread = pulse * (0.13 + 0.12 * seed);
      const scatter = dissolve * (1 - warp) * (0.38 + seed * 0.4);
      const warpContraction = warp * (airborne ? 0.47 : 0.75);
      const scale = 1 + pulseSpread + scatter - warpContraction;
      const goalX = orbitX * scale;
      const goalY = baseY * (1 + pulseSpread * 0.40 - warpContraction)
        + dissolve * (seed - 0.4) * 1.12;
      const goalZ = orbitZ * scale;

      let age = ages[i] + dt;
      const recycled = age >= lifetimes[i];
      if (recycled) age -= lifetimes[i];
      ages[i] = age;
      if (!motion || i >= lastCount || recycled) {
        positions[offset] = goalX;
        positions[offset + 1] = goalY;
        positions[offset + 2] = goalZ;
        velocities[offset] = 0;
        velocities[offset + 1] = 0;
        velocities[offset + 2] = 0;
      } else if (dt > 0) {
        const x = positions[offset];
        const y = positions[offset + 1];
        const z = positions[offset + 2];
        const dx = pointerPosition.x - x;
        const dy = pointerPosition.y - y;
        const dz = pointerPosition.z - z;
        const distance2 = dx * dx + dy * dy + dz * dz;
        const cursor = pointerStrength * (distance2 - 0.34 - pulse * 0.42)
          / ((distance2 + 0.38) * (distance2 + 0.62));
        // Each component of this curl depends only on its other two axes.
        const curlX = Math.sin(y * 1.73 + flowPhase) - Math.cos(z * 1.91 - flowPhase);
        const curlY = Math.sin(z * 1.91 + flowPhase) - Math.cos(x * 1.64 - flowPhase);
        const curlZ = Math.sin(x * 1.64 + flowPhase) - Math.cos(y * 1.73 - flowPhase);
        const force = flowAmplitude * (0.65 + seed * 0.65);
        const surge = kick * (0.35 + seed * 0.65) / (0.65 + Math.sqrt(distance2));
        const vx = (velocities[offset] + ((goalX - x) * stiffness + curlX * force + dx * cursor) * dt - dx * surge) * damping;
        const vy = (velocities[offset + 1] + ((goalY - y) * stiffness + curlY * force + dy * cursor) * dt - dy * surge) * damping;
        const vz = (velocities[offset + 2] + ((goalZ - z) * stiffness + curlZ * force + dz * cursor) * dt - dz * surge) * damping;
        velocities[offset] = vx;
        velocities[offset + 1] = vy;
        velocities[offset + 2] = vz;
        positions[offset] = x + vx * dt;
        positions[offset + 1] = y + vy * dt;
        positions[offset + 2] = z + vz * dt;
      }

      const life = motion ? Math.min(1, age * 1.6, (lifetimes[i] - age) * 1.6) : 1;
      const brightness = airborne ? 0.11 + seed * 0.13 : 0.26 + seed * 0.24;
      energy[i] = brightness * life * (1 - dissolve * 0.86) * (1 + pulse * 0.52 + warp * 0.28);

      if (i < trailCount) {
        const vertex = i * 6;
        const vx = velocities[offset];
        const vy = velocities[offset + 1];
        const vz = velocities[offset + 2];
        const speed = Math.sqrt(vx * vx + vy * vy + vz * vz);
        const length = Math.min(0.16 / Math.max(speed, 0.01), 0.074 + warp * 0.058);
        trailPositions[vertex] = positions[offset];
        trailPositions[vertex + 1] = positions[offset + 1];
        trailPositions[vertex + 2] = positions[offset + 2];
        trailPositions[vertex + 3] = positions[offset] - vx * length;
        trailPositions[vertex + 4] = positions[offset + 1] - vy * length;
        trailPositions[vertex + 5] = positions[offset + 2] - vz * length;
        trailEnergy[i * 2] = energy[i] * Math.min(0.52, Math.max(0, speed - 0.20) * (0.19 + warp * 0.25));
        trailEnergy[i * 2 + 1] = 0;
      }
    }

    pointGeometry.setDrawRange(0, count);
    pointPosition.needsUpdate = true;
    pointEnergy.needsUpdate = true;
    trails.visible = trailCount > 0;
    if (trailCount > 0) {
      trailGeometry.setDrawRange(0, trailCount * 2);
      trailPosition.needsUpdate = true;
      trailBrightness.needsUpdate = true;
    }
    lastCount = count;
    lastMotion = motion;
    lastMode = state.mode;
    lastPhase = state.phase;
    lastPulse = pulse;
  }

  return {
    update,
    dispose() {
      scene.remove(points, trails);
      pointGeometry.dispose();
      pointMaterial.dispose();
      trailGeometry.dispose();
      trailMaterial.dispose();
    },
  };
}
