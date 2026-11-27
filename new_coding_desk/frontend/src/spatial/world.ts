import * as THREE from "three";
import { createConferenceModels } from "./conferenceModels";
import {
  getTheme, MODE_THEME, SEAT_HEIGHT, SEAT_RADIUS, seatAngle,
  type SceneMode, type SceneSeat, type SpatialFrame,
} from "./sceneState";

const TAU = Math.PI * 2;
const MODES = Object.keys(MODE_THEME) as SceneMode[];

type Segment = [start: number, sweep: number];

interface ModelPose {
  size: number;
  x: number;
  z: number;
  yaw: number;
}

const arrivalPose: ModelPose = { size: 0, x: 0.38, z: -0.18, yaw: 0.6 };
const stagePose: ModelPose = { size: 1, x: 0, z: 0, yaw: 0 };
const departurePose: ModelPose = { size: 0, x: -0.59, z: -0.76, yaw: -1.02 };

function arcGeometry(
  radius: number,
  width: number,
  thickness: number,
  segments: Segment[],
  bevel = 0.012,
) {
  const inner = radius - width / 2;
  const outer = radius + width / 2;
  const depth = thickness / 2;
  const chamfer = Math.min(bevel, depth * 0.8, width * 0.42);
  const profile = chamfer > 0
    ? [
      [inner + chamfer, -depth], [outer - chamfer, -depth],
      [outer, -depth + chamfer], [outer, depth - chamfer],
      [outer - chamfer, depth], [inner + chamfer, depth],
      [inner, depth - chamfer], [inner, -depth + chamfer],
    ]
    : [[inner, -depth], [outer, -depth], [outer, depth], [inner, depth]];
  const positions: number[] = [];
  const normals: number[] = [];
  const indices: number[] = [];

  for (const [start, sweep] of segments) {
    const slices = Math.max(2, Math.ceil(sweep / 0.12));
    for (const [side, [r0, y0]] of profile.entries()) {
      const [r1, y1] = profile[(side + 1) % profile.length];
      const length = Math.hypot(r1 - r0, y1 - y0);
      const normalR = (y1 - y0) / length;
      const normalY = (r0 - r1) / length;
      const offset = positions.length / 3;
      for (let i = 0; i <= slices; i++) {
        const angle = start + sweep * i / slices;
        const x = Math.cos(angle);
        const z = -Math.sin(angle);
        positions.push(r0 * x, y0, r0 * z, r1 * x, y1, r1 * z);
        normals.push(normalR * x, normalY, normalR * z, normalR * x, normalY, normalR * z);
        if (i === slices) continue;
        const a = offset + i * 2;
        indices.push(a, a + 2, a + 3, a, a + 3, a + 1);
      }
    }
    for (const end of [false, true]) {
      const angle = start + (end ? sweep : 0);
      const x = Math.cos(angle);
      const z = -Math.sin(angle);
      const offset = positions.length / 3;
      for (const [r, y] of profile) {
        positions.push(r * x, y, r * z);
        normals.push(end ? z : -z, 0, end ? -x : x);
      }
      for (let i = 1; i < profile.length - 1; i++) {
        if (end) indices.push(offset, offset + i + 1, offset + i);
        else indices.push(offset, offset + i, offset + i + 1);
      }
    }
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute("normal", new THREE.Float32BufferAttribute(normals, 3));
  geometry.setIndex(indices);
  return geometry;
}

function radialSegments(count: number, portion: number, offset = 0): Segment[] {
  const step = TAU / count;
  return Array.from({ length: count }, (_, index) => [offset + index * step, step * portion]);
}

function makeAtmosphere(type: "ground" | "backdrop") {
  const backdrop = type === "backdrop";
  return new THREE.ShaderMaterial({
    uniforms: {
      accent: { value: new THREE.Color("#a48dec") },
      secondary: { value: new THREE.Color("#fbb28a") },
      time: { value: 0 },
      energy: { value: 0.5 },
    },
    transparent: true,
    blending: backdrop ? THREE.AdditiveBlending : THREE.NormalBlending,
    depthWrite: false,
    side: THREE.DoubleSide,
    vertexShader: `
      varying vec2 vUv;
      void main() {
        vUv = uv;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }
    `,
    fragmentShader: `
      varying vec2 vUv;
      uniform vec3 accent;
      uniform vec3 secondary;
      uniform float time;
      uniform float energy;

      float hash(vec2 v) {
        return fract(sin(dot(v, vec2(127.1, 311.7))) * 43758.5453);
      }

      void main() {
        vec2 p = vUv * 2.0 - 1.0;
        ${backdrop ? `
          float veil = 1.0 - smoothstep(0.26, 1.0, length(p));
          float stripe = p.x - p.y * 0.55;
          float beams = exp(-abs(stripe + 0.48) * 9.0)
            + 0.4 * exp(-abs(stripe + 0.26) * 18.0)
            + 0.5 * exp(-abs(stripe - 0.47) * 12.0);
          float haze = exp(-dot(p * vec2(1.6, 2.0), p * vec2(1.6, 2.0)) * 1.3);
          float grain = mix(0.86, 1.14, hash(gl_FragCoord.xy));
          float flicker = mix(0.95, 1.05, sin(p.y * 3.0 + time * 0.31) * 0.5 + 0.5);
          vec3 tint = mix(accent, secondary, smoothstep(-0.95, 0.5, p.x) * 0.62) * 0.48;
          gl_FragColor = vec4(tint, (beams * 0.19 + haze * 0.31) * veil * grain * flicker * (0.8 + energy * 0.2));
        ` : `
          float d = length(p);
          float rim = exp(-pow((d - 0.58) * 12.0, 2.0)) * 0.18;
          float wash = exp(-d * d * 10.0) * 0.48;
          float alpha = (rim + wash) * (1.0 - smoothstep(0.5, 0.96, d));
          vec3 tint = mix(accent, secondary, smoothstep(-0.72, 0.9, p.x) * 0.33) * 0.25;
          gl_FragColor = vec4(tint, alpha * (0.74 + energy * 0.31));
        `}
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }
    `,
  });
}

export function createWorld(scene: THREE.Scene): {
  update(frame: SpatialFrame): void;
  seatAnchors: ReadonlyMap<number, THREE.Object3D>;
  dispose(): void;
} {
  const world = new THREE.Group();
  world.name = "SmartDesk spatial world";
  scene.add(world);
  const geometries = new Set<THREE.BufferGeometry>();
  const materials = new Set<THREE.Material>();

  const keepMaterial = <T extends THREE.Material>(material: T): T => {
    materials.add(material);
    return material;
  };

  const mesh = <T extends THREE.Material>(
    parent: THREE.Object3D, geometry: THREE.BufferGeometry, material: T,
  ) => {
    geometries.add(geometry);
    const object = new THREE.Mesh(geometry, material);
    parent.add(object);
    return object;
  };

  const group = (parent: THREE.Object3D) => {
    const object = new THREE.Group();
    parent.add(object);
    return object;
  };

  const steel = keepMaterial(new THREE.MeshPhysicalMaterial({
    color: "#4b436b", metalness: 0.85, roughness: 0.23,
    clearcoat: 0.4, clearcoatRoughness: 0.21, envMapIntensity: 0.95,
  }));
  const edges = keepMaterial(new THREE.MeshStandardMaterial({
    color: "#9b83d5", metalness: 0.62, roughness: 0.24,
    emissive: "#8d71d3", emissiveIntensity: 0.14, envMapIntensity: 1.05,
  }));
  const darker = keepMaterial(new THREE.MeshStandardMaterial({
    color: "#24223b", metalness: 0.7, roughness: 0.38, envMapIntensity: 0.58,
  }));
  const screenSurface = keepMaterial(new THREE.MeshPhysicalMaterial({
    color: "#201c35", metalness: 0.12, roughness: 0.59,
    clearcoat: 0.28, clearcoatRoughness: 0.44, envMapIntensity: 0.16,
    emissive: "#29234a", emissiveIntensity: 0.2,
  }));
  const accentLight = keepMaterial(new THREE.MeshBasicMaterial({ color: "#bda2f9" }));
  const warmLight = keepMaterial(new THREE.MeshBasicMaterial({ color: "#f8b78a" }));
  const orbitLines = keepMaterial(new THREE.LineBasicMaterial({
    color: "#7663a8", transparent: true, opacity: 0.51,
  }));
  const arc = (
    parent: THREE.Object3D,
    material: THREE.Material,
    radius: number,
    width: number,
    height: number,
    segments: Segment[],
    bevel?: number,
  ) => mesh(parent, arcGeometry(radius, width, height, segments, bevel), material);

  const lineSegments = (parent: THREE.Object3D, points: number[], material = orbitLines) => {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(points, 3));
    geometries.add(geometry);
    const object = new THREE.LineSegments(geometry, material);
    parent.add(object);
    return object;
  };

  const studio = group(world);
  const hemisphere = new THREE.HemisphereLight("#c3b3ff", "#251735", 0.8);
  const key = new THREE.DirectionalLight("#f0eafa", 2.65);
  const side = new THREE.DirectionalLight("#9e89ff", 1.8);
  const rim = new THREE.DirectionalLight("#ffb37b", 2.4);
  const bounce = new THREE.PointLight("#e5adfe", 2.2, 4, 2);
  key.position.set(3.2, 5.4, 4.2);
  side.position.set(-4.7, 0.7, 1.8);
  rim.position.set(2, 2.4, -3.6);
  bounce.position.set(0.25, -0.57, 0.68);
  studio.add(hemisphere, key, side, rim, bounce);

  const backdrop = keepMaterial(makeAtmosphere("backdrop"));
  const backdropPlane = mesh(world, new THREE.PlaneGeometry(12, 7.2), backdrop);
  backdropPlane.position.set(-2.27, 0.65, -3.7);
  backdropPlane.rotation.y = 0.39;
  backdropPlane.renderOrder = -10;

  const ground = keepMaterial(makeAtmosphere("ground"));
  const groundPlane = mesh(world, new THREE.PlaneGeometry(8.3, 8.3), ground);
  groundPlane.position.y = -1.28;
  groundPlane.rotation.x = -Math.PI / 2;
  groundPlane.renderOrder = -9;

  const stage = group(world);
  stage.position.y = -1.03;
  const base = mesh(stage, new THREE.LatheGeometry([
    new THREE.Vector2(0, -0.24), new THREE.Vector2(1.91, -0.24),
    new THREE.Vector2(2.34, -0.12), new THREE.Vector2(2.44, -0.01),
    new THREE.Vector2(2.37, 0.045), new THREE.Vector2(2.26, 0.09),
    new THREE.Vector2(0, 0.09),
  ], 12), darker);
  base.rotation.y = Math.PI / 12;
  const deckTrim = arc(stage, steel, 2.34, 0.048, 0.027, radialSegments(12, 0.79, 0.08));
  deckTrim.position.y = 0.044;
  const innerTrim = arc(stage, edges, 1.94, 0.014, 0.007, radialSegments(9, 0.30, 0.13), 0.003);
  innerTrim.position.y = 0.102;
  const baseCut = arc(stage, darker, 1.49, 0.09, 0.028, radialSegments(6, 0.39, 0.07));
  baseCut.position.y = 0.103;

  const stageDetails: number[] = [];
  for (let i = 0; i < 90; i++) {
    const angle = i * TAU / 90;
    const x = Math.cos(angle);
    const z = Math.sin(angle);
    const inside = i % 5 === 0 ? 1.79 : 1.836;
    stageDetails.push(x * inside, 0.103, z * inside, x * 1.87, 0.103, z * 1.87);
  }
  for (let i = 0; i < 9; i++) {
    const angle = seatAngle(i + 1);
    for (const offset of [-0.016, 0.016]) {
      const x = Math.cos(angle + offset);
      const z = Math.sin(angle + offset);
      stageDetails.push(x * 2.03, 0.104, z * 2.03, x * 2.28, 0.104, z * 2.28);
    }
  }
  const detailLines = lineSegments(stage, stageDetails);

  const stator = group(world);
  const levelTrack = arc(stator, edges, 1.28, 0.016, 0.008, radialSegments(14, 0.37), 0.003);
  levelTrack.position.y = -0.82;
  const levelSegments = radialSegments(14, 0.36).map(segment => {
    const mark = arc(stator, accentLight, 1.28, 0.025, 0.01, [segment], 0.003);
    mark.position.y = -0.807;
    return mark;
  });

  const art = group(world);
  art.position.y = 0.11;

  const models = createConferenceModels(art, {
    shell: steel, bezel: darker, screen: screenSurface,
    trim: edges, accent: accentLight, warm: warmLight,
  }, mesh);

  for (const mode of MODES) {
    models[mode].root.name = `SmartDesk ${mode} form`;
    models[mode].root.visible = false;
  }

  interface SeatModel {
    anchor: THREE.Group;
    indicator: THREE.Mesh<THREE.BufferGeometry, THREE.MeshStandardMaterial>;
    ring: THREE.Mesh<THREE.BufferGeometry, THREE.MeshStandardMaterial>;
    spoke: THREE.LineSegments<THREE.BufferGeometry, THREE.LineBasicMaterial>;
    color: THREE.Color;
    focus: number;
  }

  const seatAnchors = new Map<number, THREE.Object3D>();
  const seatModels = new Map<number, SeatModel>();
  const instrument = group(world);
  const socket = new THREE.CylinderGeometry(0.113, 0.153, 0.064, 6);
  const socketRing = arcGeometry(0.164, 0.013, 0.006, radialSegments(3, 0.71), 0.003);
  const signalShape = new THREE.BoxGeometry(0.14, 0.072, 0.129);
  for (const geometry of [socket, socketRing, signalShape]) geometries.add(geometry);
  const connection = [
    0, -0.08, -0.19, 0, -0.14, -0.43,
    0, -0.14, -0.47, 0, -0.20, -0.70,
    0, -0.20, -0.74, 0, -0.28, -1.19,
  ];

  function addSeat(id: number): SeatModel {
    const angle = seatAngle(id);
    const anchor = group(instrument);
    anchor.position.set(Math.cos(angle) * SEAT_RADIUS, SEAT_HEIGHT, Math.sin(angle) * SEAT_RADIUS);
    anchor.rotation.y = Math.PI / 2 - angle;
    anchor.name = `Seat ${id}`;
    mesh(anchor, socket, darker).position.y = -0.08;
    const material = new THREE.MeshStandardMaterial({
      color: "#6b617e", emissive: "#a58ddb", emissiveIntensity: 0.24,
      metalness: 0.36, roughness: 0.22, envMapIntensity: 0.75,
    });
    const indicator = mesh(anchor, signalShape, material);
    indicator.scale.y = 1.34;
    const ring = mesh(anchor, socketRing, material);
    ring.position.y = -0.03;
    const lineMaterial = new THREE.LineBasicMaterial({
      color: "#7872ad", transparent: true, opacity: 0.22,
    });
    const spoke = lineSegments(anchor, connection, lineMaterial);
    const seat = { anchor, indicator, ring, spoke, color: new THREE.Color(), focus: 0 };
    seatAnchors.set(id, anchor);
    seatModels.set(id, seat);
    return seat;
  }

  function removeSeat(id: number, model: SeatModel) {
    instrument.remove(model.anchor);
    model.indicator.material.dispose();
    model.spoke.material.dispose();
    model.spoke.geometry.dispose();
    geometries.delete(model.spoke.geometry);
    seatAnchors.delete(id);
    seatModels.delete(id);
  }

  const accent = new THREE.Color();
  const secondary = new THREE.Color();
  const shadow = new THREE.Color();
  const previousAccent = new THREE.Color();
  const previousSecondary = new THREE.Color();
  const previousShadow = new THREE.Color();
  const themeSurface = new THREE.Color("#302944");
  const warmSeat = new THREE.Color("#ffe1a7");
  const mutedSeat = new THREE.Color("#776e8a");
  const vacantSeat = new THREE.Color("#403950");
  const readySeat = new THREE.Color("#a5ddc6");
  const seatPalette = {
    vacant: vacantSeat, assigned: mutedSeat, ready: readySeat, speaking: accent,
  };
  const seenSeats = new Set<number>();
  const previousPoses = new Map<SceneMode, ModelPose>();
  let activeMode: SceneMode | undefined;
  let level = 0;

  function updateSeat(seat: SceneSeat, frame: SpatialFrame, damping: number) {
    const model = seatModels.get(seat.id) ?? addSeat(seat.id);
    const { state, pulse } = frame;
    const selected = seat.id === state.selectedSeat;
    const speaking = seat.status === "speaking";
    const color = model.color.copy(seatPalette[seat.status]);
    if (selected) color.lerp(warmSeat, 0.64);
    model.focus = THREE.MathUtils.lerp(model.focus, selected || speaking ? 1 : 0, damping);
    const energy = 0.13 + model.focus * 0.7 + (selected || speaking ? pulse * 0.35 : 0);
    const material = model.indicator.material;
    material.color.copy(color);
    material.emissive.copy(color);
    material.emissiveIntensity = energy;
    model.indicator.position.y = -0.01 + model.focus * 0.065;
    model.indicator.scale.set(0.78 + model.focus * 0.4, 1.12 + model.focus * 0.56, 0.78 + model.focus * 0.4);
    model.ring.scale.setScalar(1 + model.focus * 0.18);
    model.spoke.material.color.copy(color);
    model.spoke.material.opacity = 0.04 + model.focus * 0.51;
    model.spoke.visible = model.focus > 0.05;
  }

  function update(frame: SpatialFrame) {
    const { state, morph, pulse, dissolve, motion, time, quality } = frame;
    const { lerp, clamp, smoothstep } = THREE.MathUtils;
    const damp = motion ? 1 - Math.exp(-Math.max(0, frame.dt) * 7) : 1;
    level = lerp(level, clamp(state.level ?? 0, 0, 1), damp);
    const theme = getTheme(state);
    const blend = smoothstep(morph, 0, 1);
    if (activeMode !== state.mode) {
      if (activeMode) {
        previousAccent.copy(accent);
        previousSecondary.copy(secondary);
        previousShadow.copy(shadow);
      } else {
        previousAccent.set(theme.accent);
        previousSecondary.set(theme.secondary);
        previousShadow.set(theme.shadow);
      }
      for (const mode of MODES) {
        const model = models[mode].root;
        previousPoses.set(mode, model.visible ? {
          size: model.scale.x, x: model.position.x, z: model.position.z, yaw: model.rotation.y,
        } : arrivalPose);
      }
      activeMode = state.mode;
    }
    accent.set(theme.accent).lerp(previousAccent, 1 - blend);
    secondary.set(theme.secondary).lerp(previousSecondary, 1 - blend);
    shadow.set(theme.shadow).lerp(previousShadow, 1 - blend);

    const activeEnergy = state.phase === "live" || state.phase === "speech" || state.phase === "vote" ? 0.11 : 0;
    steel.color.copy(themeSurface).lerp(accent, 0.26);
    darker.color.copy(shadow).lerp(themeSurface, 0.32);
    edges.color.copy(accent).lerp(themeSurface, 0.46);
    edges.emissive.copy(accent);
    edges.emissiveIntensity = 0.105 + activeEnergy * 0.4 + pulse * 0.13;
    screenSurface.color.copy(shadow).lerp(accent, 0.06);
    screenSurface.emissive.copy(shadow).lerp(accent, 0.09);
    screenSurface.emissiveIntensity = 0.2 + activeEnergy + pulse * 0.12;
    accentLight.color.copy(accent).multiplyScalar(0.82 + level * 0.26 + pulse * 0.76);
    warmLight.color.copy(secondary).multiplyScalar(0.74 + activeEnergy * 0.75 + pulse * 0.62);
    orbitLines.color.copy(accent);
    orbitLines.opacity = 0.25 + level * 0.16;
    side.color.copy(accent);
    rim.color.copy(secondary);
    bounce.color.copy(accent);
    bounce.intensity = 0.96 + level * 1.06 + pulse * 1.45;

    for (const atmosphere of [backdrop, ground]) {
      atmosphere.uniforms.accent.value.copy(accent);
      atmosphere.uniforms.secondary.value.copy(secondary);
      atmosphere.uniforms.time.value = motion ? time : 0;
      atmosphere.uniforms.energy.value = Math.min(1.4, 0.29 + level * 0.49 + pulse);
    }
    backdropPlane.visible = quality !== "low";
    detailLines.visible = quality !== "low";
    levelSegments.forEach((segment, index) => { segment.visible = (index + 0.5) / levelSegments.length <= level; });

    const artTime = motion ? time : 0;
    art.position.y = 0.11 + Math.sin(artTime * 0.55) * 0.032 + pulse * 0.036;
    art.rotation.set(
      motion ? frame.pointerY * 0.052 : 0,
      motion ? frame.pointerX * 0.061 : 0,
      Math.sin(artTime * 0.37) * 0.018,
    );
    art.scale.setScalar(1 + pulse * 0.04 - dissolve * 0.14);
    const artFrame = motion ? frame : { ...frame, time: 0 };
    for (const mode of MODES) {
      const model = models[mode];
      const from = previousPoses.get(mode) ?? arrivalPose;
      const to = state.mode === mode ? stagePose : departurePose;
      const size = lerp(from.size, to.size, blend);
      model.root.visible = size > 0.008;
      if (!model.root.visible) continue;
      model.root.scale.setScalar(size);
      model.root.position.set(lerp(from.x, to.x, blend), 0, lerp(from.z, to.z, blend));
      model.root.rotation.y = lerp(from.yaw, to.yaw, blend);
      model.animate(artFrame, level);
    }

    seenSeats.clear();
    for (const seat of state.seats ?? []) {
      seenSeats.add(seat.id);
      updateSeat(seat, frame, damp);
    }
    for (const [id, model] of seatModels) {
      if (!seenSeats.has(id)) removeSeat(id, model);
    }
  }

  function dispose() {
    scene.remove(world);
    for (const [id, model] of seatModels) removeSeat(id, model);
    for (const geometry of geometries) geometry.dispose();
    for (const material of materials) material.dispose();
  }

  return { update, seatAnchors, dispose };
}
