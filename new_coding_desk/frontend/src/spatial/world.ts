import * as THREE from "three";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import {
  getTheme, MODE_THEME, SEAT_HEIGHT, SEAT_RADIUS, seatAngle,
  type SceneMode, type SceneSeat, type SpatialFrame,
} from "./sceneState";

const TAU = Math.PI * 2;
const UP = new THREE.Vector3(0, 1, 0);
const MODES = Object.keys(MODE_THEME) as SceneMode[];

type Segment = [start: number, sweep: number];

interface StageModel {
  root: THREE.Group;
  animate(frame: SpatialFrame, level: number): void;
}

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

function jewelGeometry() {
  const points = [new THREE.Vector3(-0.17, -0.97, 0.12)];
  for (let row = 0; row < 2; row++) {
    for (let i = 0; i < 5; i++) {
      const angle = i / 5 * TAU + row * 0.42;
      const radius = (row ? 0.71 : 0.54) * (i % 2 === 0 ? 1 : 0.91);
      points.push(new THREE.Vector3(
        Math.cos(angle) * radius,
        (row ? 0.32 : -0.39) + Math.sin(i * 2.4) * 0.09,
        Math.sin(angle) * radius,
      ));
    }
  }
  points.push(new THREE.Vector3(0.16, 1, -0.09));

  const vertices: number[] = [];
  const colors: number[] = [];
  const shade = [0.5, 0.81, 1, 0.61, 0.94, 0.73, 0.87];
  const face = (a: number, b: number, c: number) => {
    const luminance = shade[(a * 7 + b * 3 + c) % shade.length];
    const color = [luminance, luminance * 0.95, Math.min(1, luminance * 1.11)];
    for (const index of [a, b, c]) {
      points[index].toArray(vertices, vertices.length);
      colors.push(...color);
    }
  };
  for (let i = 0; i < 5; i++) {
    const next = (i + 1) % 5;
    face(0, i + 1, next + 1);
    face(i + 1, i + 6, next + 6);
    face(i + 1, next + 6, next + 1);
    face(11, next + 6, i + 6);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(vertices, 3));
  geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
  geometry.computeVertexNormals();
  return geometry;
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
  const jewel = keepMaterial(new THREE.MeshPhysicalMaterial({
    color: "#e1b4b8", vertexColors: true, metalness: 0.58, roughness: 0.22,
    clearcoat: 0.9, clearcoatRoughness: 0.11,
    emissive: "#ffae83", emissiveIntensity: 0.39, envMapIntensity: 1.34,
  }));
  const accentLight = keepMaterial(new THREE.MeshBasicMaterial({ color: "#bda2f9" }));
  const warmLight = keepMaterial(new THREE.MeshBasicMaterial({ color: "#f8b78a" }));
  const orbitLines = keepMaterial(new THREE.LineBasicMaterial({
    color: "#7663a8", transparent: true, opacity: 0.51,
  }));
  const facetLines = keepMaterial(new THREE.LineBasicMaterial({
    color: "#efc9da", transparent: true, opacity: 0.28,
  }));

  const jewelShape = jewelGeometry();
  const tinyJewelShape = new THREE.OctahedronGeometry(1, 0);
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
  const pedestal = arc(stator, steel, 0.89, 0.039, 0.047, radialSegments(3, 0.67, 0.22));
  pedestal.position.y = -0.76;
  const underglow = arc(stator, warmLight, 0.78, 0.012, 0.012, radialSegments(3, 0.28, 0.31), 0);
  underglow.position.y = -0.725;
  const levelTrack = arc(stator, edges, 1.28, 0.016, 0.008, radialSegments(14, 0.37), 0.003);
  levelTrack.position.y = -0.82;
  const levelSegments = radialSegments(14, 0.36).map(segment => {
    const mark = arc(stator, accentLight, 1.28, 0.025, 0.01, [segment], 0.003);
    mark.position.y = -0.807;
    return mark;
  });

  const art = group(world);
  art.position.y = 0.11;

  // Curved ribs, raised chamfers and inset traces share a rotating axis.
  const makeRib = (parent: THREE.Object3D, radius: number, width: number, segments: Segment[]) => {
    const rib = group(parent);
    arc(rib, steel, radius, width, 0.087, segments, 0.019);
    const rimSegments: Segment[] = segments.map(([start, sweep]) => [start + 0.018, sweep - 0.036]);
    const chamfer = arc(rib, edges, radius + width * 0.27, 0.019, 0.01, rimSegments, 0.004);
    chamfer.position.y = 0.048;
    const insets: Segment[] = segments.map(([start, sweep]) => [start + sweep * 0.23, sweep * 0.51]);
    const traces = arc(rib, accentLight, radius - width * 0.24, 0.014, 0.01, insets, 0.002);
    traces.position.y = 0.05;
    return rib;
  };

  const room = group(art);
  const roomCrystal = mesh(room, jewelShape, jewel);
  roomCrystal.scale.set(0.94, 1.03, 0.94);
  const facets = new THREE.EdgesGeometry(jewelShape, 27).scale(1.003, 1.003, 1.003);
  geometries.add(facets);
  roomCrystal.add(new THREE.LineSegments(facets, facetLines));
  const roomOrbits = [
    makeRib(room, 1.19, 0.186, [[-0.73, 1.51], [1.24, 1.36], [3.07, 1.65], [5.00, 0.31]]),
    makeRib(room, 1.35, 0.1, [[0.08, 1.12], [1.58, 0.6], [3.10, 1.48], [5.02, 0.7]]),
    makeRib(room, 0.96, 0.078, [[0.27, 0.68], [2.23, 1.47], [4.47, 0.74]]),
  ];
  const wings = group(room);
  for (const [index, angle] of [0.1, 1.8, 3.22, 4.75].entries()) {
    const blade = mesh(wings, jewelShape, index % 2 ? edges : steel);
    blade.position.set(Math.cos(angle) * 0.76, index % 2 ? -0.23 : 0.23, Math.sin(angle) * 0.76);
    blade.scale.set(0.23, 0.54, 0.27);
    blade.rotation.set(Math.sin(angle) * 0.77, angle, Math.cos(angle) * 0.71);
  }

  const agenda = group(art);
  const agendaSpindle = mesh(agenda, jewelShape, jewel);
  agendaSpindle.scale.set(0.48, 0.98, 0.48);
  const agendaDiscs = [0.53, 0.8, 1.11, 1.27].map((radius, index) => {
    const disc = makeRib(agenda, radius, 0.16 - index * 0.014, radialSegments(3, 0.76, 0.32));
    disc.position.y = 0.7 - index * 0.43;
    return disc;
  });

  const service = group(art);
  const serviceCore = mesh(service, jewelShape, jewel);
  serviceCore.scale.setScalar(0.76);
  const network = group(service);
  const constellation = [
    new THREE.Vector3(-0.88, 0.45, 0.04), new THREE.Vector3(-0.6, -0.49, 0.74),
    new THREE.Vector3(0.22, 0.83, -0.57), new THREE.Vector3(0.81, 0.36, 0.39),
    new THREE.Vector3(0.73, -0.4, -0.59), new THREE.Vector3(0.11, -0.86, 0.13),
  ];
  const struts: THREE.BufferGeometry[] = [];
  const wire: number[] = [];
  const addStrut = (start: THREE.Vector3, end: THREE.Vector3, radius: number) => {
    const direction = end.clone().sub(start);
    const rotation = new THREE.Quaternion().setFromUnitVectors(UP, direction.clone().normalize());
    const at = start.clone().lerp(end, 0.5);
    struts.push(new THREE.CylinderGeometry(radius, radius * 0.74, direction.length(), 5)
      .applyQuaternion(rotation).translate(at.x, at.y, at.z));
  };
  constellation.forEach((point, index) => {
    const node = mesh(network, jewelShape, index % 2 ? jewel : edges);
    node.position.copy(point);
    node.scale.set(0.25, 0.26, 0.25);
    node.rotation.set(0.63, index * 1.7, index * 0.46);
    addStrut(new THREE.Vector3(), point, 0.024);
    const next = constellation[(index + 2) % constellation.length];
    if (index === 4 || index === 5) return;
    wire.push(point.x, point.y, point.z, next.x, next.y, next.z);
  });
  const mergedStruts = mergeGeometries(struts);
  struts.forEach(geometry => geometry.dispose());
  mesh(network, mergedStruts, steel);
  lineSegments(network, wire);

  const station = group(art);
  const stationGem = mesh(station, jewelShape, jewel);
  stationGem.scale.set(0.81, 1.14, 0.81);
  const stationHalo = makeRib(station, 1.12, 0.144, radialSegments(3, 0.74, 0.4));
  const stationArms = group(station);
  for (let i = 0; i < 3; i++) {
    const pivot = group(stationArms);
    pivot.rotation.y = i / 3 * TAU + 0.3;
    const prong = mesh(pivot, jewelShape, steel);
    prong.scale.set(0.27, 0.76, 0.25);
    prong.position.set(0.80, -0.09, 0);
    prong.rotation.z = -0.44;
  }

  const display = group(art);
  const eclipse = group(display);
  mesh(eclipse, new THREE.SphereGeometry(0.83, 32, 16), darker).scale.z = 0.71;
  const corona = arc(eclipse, edges, 0.876, 0.03, 0.022, radialSegments(3, 0.97), 0.008);
  corona.rotation.x = Math.PI / 2;
  const luminousCorona = arc(eclipse, warmLight, 0.894, 0.021, 0.01, [[-0.72, 1.35], [1.1, 0.29]], 0.004);
  luminousCorona.rotation.x = Math.PI / 2;
  const displayOrbital = makeRib(display, 1.22, 0.2, [[-0.7, 1.87], [2.18, 1.58], [4.18, 0.82]]);
  const displaySignal = mesh(eclipse, tinyJewelShape, jewel);
  displaySignal.scale.setScalar(0.143);
  displaySignal.position.set(0.91, 0.26, 0.12);

  const relay = group(art);
  const relayCore = mesh(relay, jewelShape, jewel);
  relayCore.scale.set(0.35, 0.84, 0.35);
  const apertures = [0.67, 0.95, 1.26].map((radius, index) => {
    const ap = makeRib(relay, radius, 0.22 - index * 0.025, radialSegments(4, 0.42, index * 0.29));
    ap.position.z = (index - 1) * -0.28;
    return ap;
  });

  const identity = group(art);
  const prisms = [
    mesh(identity, jewelShape, jewel),
    mesh(identity, jewelShape, steel),
  ];
  const innerPrisms = [
    mesh(identity, jewelShape, edges),
    mesh(identity, jewelShape, warmLight),
  ];
  const signature = makeRib(identity, 1.1, 0.09, [[-0.48, 1.36], [2.52, 1.92]]);
  const identityCenter = mesh(identity, tinyJewelShape, accentLight);
  identityCenter.scale.set(0.09, 0.14, 0.09);

  const models: Record<SceneMode, StageModel> = {
    room: {
      root: room,
      animate: ({ time, pulse, warp }, level) => {
        roomCrystal.rotation.set(0.24 + Math.sin(time * 0.38) * 0.13, time * 0.27 + 0.2, -0.2);
        roomOrbits[0].rotation.set(0.33, time * 0.19, 0.76 + level * 0.12);
        roomOrbits[1].rotation.set(1.16 + Math.sin(time * 0.44) * 0.15, -time * 0.16, -0.66);
        roomOrbits[2].rotation.set(1.22, time * 0.30, 0.29);
        roomOrbits[1].scale.setScalar(1 + pulse * 0.045 + warp * 0.07);
        wings.rotation.y = -time * 0.26;
        wings.scale.setScalar(1 + level * 0.09 + pulse * 0.1);
      },
    },
    agenda: {
      root: agenda,
      animate: ({ time, pulse }, level) => {
        agendaSpindle.rotation.set(-0.11, time * 0.34, 0.16);
        agendaDiscs.forEach((disc, index) => {
          disc.rotation.set(index * 0.18, time * (index % 2 ? -0.43 : 0.28) + index, -0.38 + index * 0.10);
          disc.position.y = (0.7 - index * 0.43) * (0.85 + level * 0.31 + pulse * 0.14);
        });
      },
    },
    service: {
      root: service,
      animate: ({ time, pulse }, level) => {
        serviceCore.rotation.set(0.12, -time * 0.32, 0.21);
        network.rotation.set(Math.sin(time * 0.29) * 0.22, time * 0.30 + 0.18, -0.18);
        network.scale.setScalar(0.93 + level * 0.13 + pulse * 0.11);
      },
    },
    station: {
      root: station,
      animate: ({ time, pulse }, level) => {
        stationGem.rotation.set(-0.21, time * 0.31, -0.13);
        stationHalo.rotation.set(0.22, -time * 0.27, 0.19);
        stationHalo.position.y = -0.19 + level * 0.2;
        stationArms.rotation.y = time * 0.31;
        stationArms.scale.setScalar(1 + pulse * 0.12);
      },
    },
    display: {
      root: display,
      animate: ({ time, pulse }, level) => {
        eclipse.rotation.set(-0.15, -0.13 + Math.sin(time * 0.32) * 0.26, 0.19);
        displayOrbital.rotation.set(1.01 + 0.21 * level, time * 0.37, -0.45);
        displayOrbital.scale.setScalar(1 + pulse * 0.07);
        displaySignal.position.set(Math.cos(time * 0.46 + 0.29), Math.sin(time * 0.46 + 0.29), 0.08);
      },
    },
    relay: {
      root: relay,
      animate: ({ time, pulse }, level) => {
        relayCore.rotation.set(0.17, time * 0.51, -0.23);
        apertures.forEach((ap, index) => {
          ap.rotation.set(Math.PI / 2 - 0.19 * index, 0.23 - index * 0.12, time * 0.36 * (index % 2 ? -1 : 1));
          ap.position.z = (index - 1) * (-0.27 - level * 0.18);
          ap.scale.setScalar(1 + pulse * (0.06 + index * 0.02));
        });
      },
    },
    identity: {
      root: identity,
      animate: ({ time, pulse }, level) => {
        signature.rotation.set(0.29, time * -0.38, -0.43);
        identityCenter.rotation.y = time * 0.48;
        prisms.forEach((prism, index) => {
          const direction = index ? 1 : -1;
          const offset = (0.39 + level * 0.12 + pulse * 0.10) * direction;
          prism.scale.set(0.46, 1.02, 0.62);
          prism.position.set(offset, direction * 0.17, direction * 0.11);
          prism.rotation.set(direction * 0.26, time * 0.23 + direction * 0.35, direction * -0.44);
          innerPrisms[index].scale.set(0.18, 0.53, 0.29);
          innerPrisms[index].position.set(offset * 1.66, direction * 0.24, direction * 0.20);
          innerPrisms[index].rotation.copy(prism.rotation);
        });
      },
    },
  };

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
  const signalShape = new THREE.OctahedronGeometry(0.093, 0);
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
    const { state, time, pulse } = frame;
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
    model.indicator.rotation.y = frame.motion ? time * 0.42 + seat.id : seat.id;
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
    jewel.color.copy(secondary).lerp(accent, 0.28).multiplyScalar(0.64);
    jewel.emissive.copy(secondary).lerp(accent, 0.38);
    jewel.emissiveIntensity = (0.135 + activeEnergy + level * 0.12 + pulse * 0.30) * (1 - dissolve * 0.45);
    accentLight.color.copy(accent).multiplyScalar(0.82 + level * 0.26 + pulse * 0.76);
    warmLight.color.copy(secondary).multiplyScalar(0.74 + activeEnergy * 0.75 + pulse * 0.62);
    orbitLines.color.copy(accent);
    orbitLines.opacity = 0.25 + level * 0.16;
    facetLines.color.copy(secondary).lerp(accent, 0.2);
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
    art.position.y = 0.11 + Math.sin(artTime * 0.65) * 0.09 + pulse * 0.07;
    art.rotation.set(
      motion ? frame.pointerY * 0.12 - Math.sin(artTime * 0.27) * 0.06 : 0,
      motion ? frame.pointerX * 0.13 : 0,
      Math.sin(artTime * 0.37) * 0.043,
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
