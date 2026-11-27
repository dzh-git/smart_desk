import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { SEAT_RADIUS, seatAngle, type SceneMode, type SpatialFrame } from "./sceneState";

interface Model {
  root: THREE.Group;
  animate(frame: SpatialFrame, level: number): void;
}

interface Materials {
  shell: THREE.Material;
  bezel: THREE.Material;
  screen: THREE.Material;
  trim: THREE.Material;
  accent: THREE.Material;
  warm: THREE.Material;
}

type AddMesh = (parent: THREE.Object3D, geometry: THREE.BufferGeometry, material: THREE.Material) => THREE.Mesh;

export function createConferenceModels(art: THREE.Group, materials: Materials, mesh: AddMesh): Record<SceneMode, Model> {
  const { shell, bezel, screen, trim, accent, warm } = materials;
  const boxShape = new THREE.BoxGeometry(1, 1, 1);
  const roundedShape = new RoundedBoxGeometry(1, 1, 1, 2, 0.09);
  const knobShape = new THREE.SphereGeometry(0.5, 16, 10);
  const tableShape = new THREE.CylinderGeometry(1, 1, 1, 56);
  const cupShape = new THREE.LatheGeometry([
    new THREE.Vector2(0, 0), new THREE.Vector2(0.27, 0), new THREE.Vector2(0.35, 0.07),
    new THREE.Vector2(0.45, 0.70), new THREE.Vector2(0.41, 0.73), new THREE.Vector2(0.37, 0.67),
    new THREE.Vector2(0.30, 0.11), new THREE.Vector2(0, 0.11),
  ], 40);
  const handleShape = new THREE.TorusGeometry(0.28, 0.042, 10, 30, Math.PI * 2);

  const group = (parent: THREE.Object3D, name = "") => {
    const object = new THREE.Group();
    object.name = name;
    parent.add(object);
    return object;
  };

  function shape(parent: THREE.Object3D, geometry: THREE.BufferGeometry, material: THREE.Material,
    width: number, height: number, depth: number, x = 0, y = 0, z = 0) {
    const object = mesh(parent, geometry, material);
    object.scale.set(width, height, depth);
    object.position.set(x, y, z);
    return object;
  }

  function block(parent: THREE.Object3D, material: THREE.Material,
    width: number, height: number, depth: number, x = 0, y = 0, z = 0) {
    return shape(parent, roundedShape, material, width, height, depth, x, y, z);
  }

  function stroke(parent: THREE.Object3D, material: THREE.Material, width: number, x: number, y: number, z: number) {
    return shape(parent, boxShape, material, width, 0.027, 0.012, x, y, z);
  }

  function panel(parent: THREE.Object3D, width: number, height: number, x: number, y: number, z: number, name: string) {
    const display = group(parent, name);
    display.position.set(x, y, z);
    block(display, trim, width, height, 0.098);
    block(display, screen, width - 0.075, height - 0.072, 0.072, 0, 0, 0.027);
    stroke(display, accent, width * 0.26, -width * 0.29, height * 0.5 - 0.025, 0.068);
    return display;
  }

  function wave(parent: THREE.Object3D, width: number, x: number, y: number, z: number, material: THREE.Material) {
    const waveGroup = group(parent);
    waveGroup.position.set(x, y, z);
    return Array.from({ length: 13 }, (_, index) => {
      const bar = shape(waveGroup, boxShape, material, 0.027, 1, 0.016, (index / 12 - 0.5) * width);
      bar.scale.y = 0.055;
      return bar;
    });
  }

  function updateWave(bars: THREE.Mesh[], time: number, strength: number, min = 0.032) {
    bars.forEach((bar, index) => {
      const envelope = Math.sin((index + 1) * Math.PI / (bars.length + 1));
      bar.scale.y = min + Math.abs(Math.sin(time * 4.5 + index * 1.49)) * envelope * strength;
    });
  }

  const room = group(art);
  const conferenceTable = group(room, "Conference table");
  shape(conferenceTable, tableShape, shell, 0.51, 0.30, 0.42, 0, -0.88);
  shape(conferenceTable, tableShape, trim, 1.57, 0.12, 1.43, 0, -0.58);
  shape(conferenceTable, tableShape, shell, 1.55, 0.13, 1.41, 0, -0.52);
  shape(conferenceTable, tableShape, trim, 1.02, 0.022, 0.80, 0, -0.446);
  shape(conferenceTable, tableShape, screen, 0.99, 0.035, 0.77, 0, -0.431);
  const hub = panel(conferenceTable, 1.30, 0.73, 0, -0.06, 0, "Shared table agenda");
  hub.rotation.x = -0.38;
  const hubWave = wave(hub, 0.91, 0, 0.05, 0.072, accent);
  stroke(hub, trim, 0.57, -0.17, -0.19, 0.072);
  stroke(hub, warm, 0.19, 0.33, -0.19, 0.072);
  for (let id = 1; id <= 9; id++) {
    const angle = seatAngle(id);
    const chair = group(conferenceTable, `Conference chair ${id}`);
    chair.position.set(Math.cos(angle) * (SEAT_RADIUS - 0.13), -0.86, Math.sin(angle) * (SEAT_RADIUS - 0.13));
    chair.rotation.y = Math.PI / 2 - angle;
    block(chair, shell, 0.46, 0.105, 0.37, 0, 0, 0);
    block(chair, id === 1 ? trim : bezel, 0.46, 0.29, 0.093, 0, 0.14, 0.15);
    block(chair, id === 1 ? warm : trim, 0.27, 0.022, 0.04, 0, 0.245, 0.203);
  }

  const agenda = group(art);
  const agendaBook = panel(agenda, 2.83, 1.65, 0, -0.09, 0, "Agenda list");
  agendaBook.rotation.y = 0.22;
  block(agendaBook, trim, 0.75, 0.48, 0.039, -0.82, 0.29, 0.067);
  for (let day = 0; day < 3; day++) {
    block(agendaBook, day === 1 ? warm : accent, 0.13, 0.13, 0.015, -1.03 + day * 0.20, 0.28, 0.094);
  }
  const agendaProgress = block(agendaBook, warm, 1, 0.053, 0.015, 0, -0.58, 0.085);
  block(agendaBook, bezel, 2.12, 0.069, 0.012, 0, -0.58, 0.076);
  for (let index = 0; index < 3; index++) {
    const y = 0.45 - index * 0.32;
    block(agendaBook, index === 0 ? warm : trim, 0.086, 0.086, 0.021, -0.17, y, 0.075);
    stroke(agendaBook, index === 0 ? accent : trim, 0.99 - index * 0.20, 0.55 - index * 0.10, y, 0.074);
    stroke(agendaBook, trim, 0.61 - index * 0.11, 0.35 - index * 0.055, y - 0.105, 0.074);
  }
  const agendaBack = panel(agenda, 2.7, 1.42, 0.38, 0.035, -0.26, "Agenda documents");
  agendaBack.rotation.y = 0.29;

  const vote = group(art);
  const chart = panel(vote, 3.08, 1.74, 0, -0.02, 0, "Live meeting ballot");
  chart.rotation.y = 0.22;
  const chartStart = -0.60;
  for (let index = 0; index < 4; index++) stroke(chart, trim, 2.62, 0, chartStart + index * 0.35, 0.069);
  const columns = Array.from({ length: 5 }, (_, index) => {
    const column = group(chart, `Vote option ${index + 1}`);
    block(column, index === 0 ? accent : warm, 0.24, 1, 0.13, 0, 0.5, 0.14);
    block(column, trim, 0.31, 0.07, 0.20, 0, 0.023, 0.12);
    return column;
  });

  const captions = group(art);
  const upperCaption = panel(captions, 2.85, 0.62, -0.16, 0.38, 0, "Original speech captions");
  const translated = panel(captions, 2.72, 0.62, 0.19, -0.37, -0.06, "Translated captions");
  const captionWaves = [upperCaption, translated].map((caption, index) => {
    block(caption, index ? warm : accent, 0.17, 0.14, 0.022, -1.10, 0.04, 0.075);
    stroke(caption, trim, 0.31, -1.03, -0.12, 0.075);
    return wave(caption, 1.45, 0.39, 0, 0.074, index ? warm : accent);
  });

  const service = group(art);
  const tray = group(service, "Meeting refreshment service");
  shape(tray, tableShape, shell, 1.52, 0.11, 0.88, 0, -0.68);
  shape(tray, tableShape, trim, 1.41, 0.026, 0.79, 0, -0.615);
  for (const [index, x] of [-0.80, 0.04, 0.87].entries()) {
    const cup = group(tray, `Service vessel ${index + 1}`);
    const size = index === 1 ? 0.96 : 0.68;
    cup.position.set(x, -0.58, index === 1 ? 0.20 : -0.07);
    cup.scale.setScalar(size);
    mesh(cup, cupShape, index === 1 ? trim : shell);
    if (index !== 2) shape(cup, handleShape, trim, 0.78, 0.77, 0.75, 0.45, 0.39);
    shape(cup, tableShape, index === 1 ? warm : accent, 0.32, 0.021, 0.32, 0, 0.54);
  }
  const serviceIndicator = panel(service, 0.94, 0.37, 0.68, 0.48, -0.26, "Service request signal");
  serviceIndicator.rotation.y = 0.36;
  const requestLights = [-0.25, 0, 0.25].map((x) => block(serviceIndicator, accent, 0.12, 0.075, 0.015, x, -0.012, 0.075));

  const station = group(art);
  const terminal = group(station, "Participant seat console");
  terminal.rotation.y = 0.24;
  const terminalMonitor = panel(terminal, 2.32, 1.35, -0.22, 0.13, 0, "Seat touchscreen");
  terminalMonitor.rotation.x = -0.26;
  block(terminal, shell, 2.58, 0.13, 1.35, -0.1, -0.63, 0.04);
  block(terminal, trim, 1.47, 0.04, 0.15, -0.57, -0.544, 0.61);
  block(terminalMonitor, trim, 0.57, 0.65, 0.028, -0.64, -0.04, 0.071);
  shape(terminalMonitor, knobShape, accent, 0.21, 0.21, 0.06, -0.64, 0.08, 0.096);
  block(terminalMonitor, accent, 0.30, 0.090, 0.029, -0.64, -0.12, 0.105);
  stroke(terminalMonitor, trim, 0.77, 0.35, -0.24, 0.074);
  const deskWave = wave(terminalMonitor, 0.80, 0.34, 0.05, 0.074, accent);
  const micStand = group(terminal, "Seat microphone");
  micStand.position.set(1.12, -0.53, 0.28);
  shape(micStand, tableShape, trim, 0.17, 0.065, 0.16);
  const micStem = block(micStand, shell, 0.051, 0.71, 0.054, 0, 0.34, 0);
  micStem.rotation.z = -0.14;
  const microphone = block(micStand, warm, 0.15, 0.30, 0.145, 0.065, 0.77, 0);
  microphone.rotation.z = 0.31;

  const display = group(art);
  const presentation = panel(display, 3.79, 1.97, 0, 0.11, 0, "Meeting presentation screen");
  presentation.rotation.y = 0.19;
  block(presentation, shell, 0.13, 0.47, 0.115, 0, -1.13);
  block(presentation, trim, 1.16, 0.13, 0.39, 0, -1.25);
  block(presentation, bezel, 1.63, 1.15, 0.015, -0.81, 0, 0.077);
  block(presentation, trim, 1.36, 0.085, 0.014, -0.83, 0.37, 0.088);
  stroke(presentation, warm, 0.49, -1.17, 0.17, 0.088);
  const presentationWave = wave(presentation, 1.13, -0.78, -0.12, 0.093, accent);
  for (let index = 0; index < 3; index++) {
    const y = 0.44 - index * 0.34;
    block(presentation, index === 0 ? warm : trim, 0.092, 0.092, 0.016, 0.36, y, 0.071);
    stroke(presentation, accent, 0.80 - index * 0.11, 0.95 - index * 0.055, y, 0.072);
    stroke(presentation, trim, 0.45, 0.77, y - 0.11, 0.072);
  }

  const relay = group(art);
  const source = panel(relay, 1.36, 0.92, -1.14, -0.19, 0.32, "Share source");
  source.rotation.y = 0.29;
  block(source, shell, 1.49, 0.068, 0.67, 0, -0.497, 0.32);
  block(source, trim, 0.61, 0.016, 0.26, 0, -0.46, 0.30);
  const receiver = panel(relay, 2.38, 1.51, 0.78, 0.12, -0.22, "Share destination");
  receiver.rotation.y = 0.33;
  block(receiver, trim, 0.11, 0.31, 0.13, 0, -0.89);
  block(receiver, shell, 1.35, 0.089, 0.31, 0, -1.02);
  for (const [target, width] of [[source, 1], [receiver, 1.91]] as const) {
    for (let index = 0; index < 3; index++) stroke(target, index === 0 ? accent : trim, width * (1 - index * 0.21), -index * 0.08, 0.17 - index * 0.18, 0.072);
  }
  const signalPath = Array.from({ length: 7 }, (_, index) => {
    const step = index / 6;
    const packet = block(relay, index % 2 ? warm : accent, 0.081, 0.084, 0.079,
      -0.74 + step * 1.70, 0.41 + Math.sin(step * Math.PI) * 0.57, 0.4 - step * 0.29);
    packet.rotation.z = Math.PI / 4;
    return packet;
  });

  const identity = group(art);
  const scanPanel = panel(identity, 2.37, 1.76, 0, 0, 0, "Seat identity scan");
  scanPanel.rotation.y = 0.26;
  block(scanPanel, bezel, 1.09, 1.22, 0.021, 0, 0, 0.070);
  shape(scanPanel, knobShape, trim, 0.49, 0.59, 0.17, 0, 0.19, 0.17);
  shape(scanPanel, knobShape, shell, 0.79, 0.37, 0.15, 0, -0.29, 0.16);
  for (const x of [-1, 1]) for (const y of [-1, 1]) {
    block(scanPanel, accent, 0.23, 0.04, 0.036, x * 0.48, y * 0.58, 0.104);
    block(scanPanel, accent, 0.04, 0.23, 0.036, x * 0.58, y * 0.48, 0.104);
  }
  const scanner = stroke(scanPanel, warm, 1.19, 0, 0, 0.28);

  return {
    room: {
      root: room,
      animate: ({ state, time, pulse }, level) => updateWave(hubWave, time,
        state.phase === "speech" ? 0.31 + pulse * 0.11 : 0.10 + level * 0.10),
    },
    agenda: {
      root: agenda,
      animate: ({ pulse }, level) => {
        agendaProgress.scale.x = Math.max(0.02, level * 2.12);
        agendaProgress.position.x = -1.06 + agendaProgress.scale.x / 2;
        agendaBack.position.z = -0.26 - pulse * 0.16;
        agendaBack.position.x = 0.38 + pulse * 0.13;
      },
    },
    vote: {
      root: vote,
      animate: ({ state, motion, dt }) => {
        const shares = state.voteShares?.slice(0, columns.length) ?? [];
        const spacing = 2.55 / Math.max(shares.length, 1);
        const damping = motion ? 1 - Math.exp(-12 * dt) : 1;
        columns.forEach((column, index) => {
          column.visible = index < shares.length;
          if (!column.visible) return;
          column.position.set((index - (shares.length - 1) / 2) * spacing, chartStart, 0.050);
          column.scale.set(Math.min(spacing * 2.12, 1.9),
            THREE.MathUtils.lerp(column.scale.y, 0.073 + shares[index] * 1.16, damping), 1);
        });
      },
    },
    captions: {
      root: captions,
      animate: ({ state, time, pulse }) => {
        upperCaption.rotation.y = 0.20 + pulse * 0.09;
        translated.rotation.y = 0.3 - pulse * 0.13;
        captionWaves.forEach((bars, index) => updateWave(bars, time - index * 0.38,
          state.phase === "speech" ? 0.32 : 0.11));
      },
    },
    service: {
      root: service,
      animate: ({ pulse, time }, level) => {
        serviceIndicator.position.y = 0.47 + pulse * 0.15;
        requestLights.forEach((light, index) => {
          const responding = index < Math.ceil(level * requestLights.length);
          light.scale.y = responding ? 0.072 + pulse * 0.043 + Math.sin(time * 2 + index) * 0.014 : 0.024;
        });
      },
    },
    station: {
      root: station,
      animate: ({ state, time, pulse }) => {
        terminalMonitor.rotation.x = -0.26 - pulse * 0.09;
        updateWave(deskWave, time, state.phase === "speech" ? 0.42 : 0.125);
        microphone.scale.x = 0.15 + (state.phase === "speech" ? pulse * 0.04 : 0);
      },
    },
    display: {
      root: display,
      animate: ({ time, pulse }, level) => updateWave(presentationWave, time, 0.18 + level * 0.17 + pulse * 0.16),
    },
    relay: {
      root: relay,
      animate: ({ state, time, pulse }) => {
        const connected = state.signal === "online";
        signalPath.forEach((packet, index) => {
          const glow = Math.max(0, Math.sin(time * 3.6 - index * 0.79));
          packet.scale.setScalar((connected ? 0.093 : 0.048) + glow * 0.037 + pulse * 0.038);
        });
      },
    },
    identity: {
      root: identity,
      animate: ({ state, time, pulse }) => {
        scanner.position.y = state.phase === "busy" ? Math.sin(time * 2.8) * 0.51 : pulse * 0.35;
      },
    },
  };
}
