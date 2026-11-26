import {
  MathUtils, PerspectiveCamera, PMREMGenerator, Scene, Vector3, WebGLRenderer,
} from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { createDirector } from "./director";
import { createLens } from "./lens";
import { createParticles } from "./particles";
import { createWorld } from "./world";
import type { RenderQuality, SceneQuality, SpatialState } from "./sceneState";

interface EngineOptions {
  quality: SceneQuality;
  motion: boolean;
}

interface FrameMetrics {
  fps: number;
  quality: RenderQuality;
}

export interface SpatialEngine {
  resize(width: number, height: number): void;
  setState(state: SpatialState): void;
  setOptions(options: EngineOptions): void;
  setVisible(visible: boolean): void;
  movePointer(x: number, y: number): void;
  orbit(dx: number, dy: number): void;
  pickSeat(x: number, y: number): number | null;
  dispose(): void;
}

const QUALITY_LEVELS = ["low", "medium", "high"] as const;
const QUALITY_LIMITS: Record<RenderQuality, { dpr: number; pixels: number }> = {
  high: { dpr: 1.65, pixels: 1_650_000 },
  medium: { dpr: 1.3, pixels: 1_050_000 },
  low: { dpr: 1, pixels: 580_000 },
};

function usesSoftwareRenderer(context: WebGL2RenderingContext) {
  const info = context.getExtension("WEBGL_debug_renderer_info");
  return info !== null && /swiftshader|llvmpipe|software rasterizer/i.test(context.getParameter(info.UNMASKED_RENDERER_WEBGL));
}

function createEnvironment(renderer: WebGLRenderer) {
  if (!renderer.extensions.has("EXT_color_buffer_float")) return null;
  const environment = new RoomEnvironment();
  const generator = new PMREMGenerator(renderer);
  try {
    return generator.fromScene(environment, 0.035, 0.1, 45, { size: 64 });
  } finally {
    environment.dispose();
    generator.dispose();
  }
}

export function createSpatialEngine(canvas: HTMLCanvasElement, onFrame?: (metrics: FrameMetrics) => void): SpatialEngine {
  const browser = canvas.ownerDocument.defaultView ?? window;
  const context = canvas.getContext("webgl2", {
    alpha: true,
    antialias: false,
    depth: true,
    premultipliedAlpha: true,
    stencil: false,
    powerPreference: "high-performance",
  });
  if (!context) throw new Error("WebGL2 is unavailable");

  const softwareRenderer = usesSoftwareRenderer(context);
  const renderer = new WebGLRenderer({ canvas, context, alpha: true });
  renderer.setClearColor(0, 0);
  const scene = new Scene();
  const camera = new PerspectiveCamera(35, 1, 0.08, 64);
  const position = new Vector3();
  const cleanups = [() => renderer.dispose()];
  function release() {
    while (cleanups.length > 0) cleanups.pop()?.();
  }

  const { world, particles, lens } = (() => {
    try {
      const environment = createEnvironment(renderer);
      if (environment) {
        scene.environment = environment.texture;
        scene.environmentIntensity = 0.74;
        cleanups.push(() => environment.dispose());
      }
      const world = createWorld(scene);
      cleanups.push(world.dispose);
      const particles = createParticles(scene);
      cleanups.push(particles.dispose);
      const lens = createLens(renderer, context);
      cleanups.push(lens.dispose);
      return { world, particles, lens };
    } catch (error) {
      release();
      throw error;
    }
  })();

  let director: ReturnType<typeof createDirector> | null = null;
  let motion = true;
  let visible = true;
  let disposed = false;
  let width = 0;
  let height = 0;
  let deviceRatio = 1;
  let sizeDirty = true;
  let baseFov = camera.fov;
  let request: number | null = null;
  let previousTime: number | null = null;
  let qualityMode: SceneQuality = "auto";
  let adaptiveQuality: RenderQuality = softwareRenderer || browser.matchMedia?.("(pointer: coarse) and (max-width: 800px)")?.matches
    ? "medium" : "high";
  let quality: RenderQuality = adaptiveQuality;
  let metricTime = 0;
  let metricFrames = 0;
  let quickWindows = 0;
  let slowWindows = 0;
  let lastFps = 0;

  function reconcileSize() {
    sizeDirty = false;
    const limits = QUALITY_LIMITS[quality];
    const maxTexture = renderer.capabilities.maxTextureSize;
    const automaticLimit = softwareRenderer && qualityMode === "auto" ? 0.85 : limits.dpr;
    const dpr = Math.min(deviceRatio, limits.dpr, automaticLimit,
      Math.sqrt(limits.pixels / (width * height)), maxTexture / Math.max(width, height));
    renderer.setDrawingBufferSize(width, height, dpr);
    lens.setSize(Math.max(1, canvas.width), Math.max(1, canvas.height), quality);
    camera.aspect = width / height;
    const tangent = Math.max(Math.tan(MathUtils.degToRad(17.5)), 0.365 / camera.aspect);
    baseFov = MathUtils.radToDeg(2 * Math.atan(tangent));
    camera.updateProjectionMatrix();
  }

  function stop() {
    if (request !== null) browser.cancelAnimationFrame(request);
    request = null;
    previousTime = null;
    metricFrames = 0;
    metricTime = 0;
    quickWindows = 0;
    slowWindows = 0;
  }

  function schedule() {
    if (request !== null || disposed || !visible || !director || width <= 0 || height <= 0) return;
    request = browser.requestAnimationFrame(render);
  }

  function setQuality(next: RenderQuality) {
    if (next === quality) return;
    quality = next;
    sizeDirty = true;
    quickWindows = 0;
    slowWindows = 0;
  }

  function samplePerformance(elapsed: number) {
    metricTime += elapsed;
    metricFrames++;
    if (metricTime < 1100) return;
    lastFps = 1000 * metricFrames / metricTime;
    metricFrames = 0;
    metricTime = 0;

    if (qualityMode === "auto") {
      const index = QUALITY_LEVELS.indexOf(adaptiveQuality);
      slowWindows = lastFps < 43 ? slowWindows + 1 : 0;
      quickWindows = lastFps > 56 ? quickWindows + 1 : 0;
      if (slowWindows >= 2 && index > 0) adaptiveQuality = QUALITY_LEVELS[index - 1];
      else if (quickWindows >= 5 && index < QUALITY_LEVELS.length - 1) adaptiveQuality = QUALITY_LEVELS[index + 1];
      setQuality(adaptiveQuality);
    }
    onFrame?.({ fps: lastFps, quality });
  }

  function render(timestamp: number) {
    request = null;
    if (!director || !visible || disposed || width <= 0 || height <= 0 || renderer.getContext().isContextLost()) return;
    if (sizeDirty) reconcileSize();
    const elapsed = previousTime === null ? null : timestamp - previousTime;
    previousTime = motion ? timestamp : null;

    const { pose, frame } = director.advance(elapsed === null ? 1 / 60 : elapsed / 1000, quality);
    const fov = baseFov + frame.warp * 14;
    if (camera.fov !== fov) {
      camera.fov = fov;
      camera.updateProjectionMatrix();
    }
    const horizontal = pose.distance * Math.cos(pose.elevation);
    camera.position.set(
      horizontal * Math.sin(pose.yaw),
      pose.targetY + pose.distance * Math.sin(pose.elevation),
      horizontal * Math.cos(pose.yaw),
    );
    camera.lookAt(0, pose.targetY, 0);
    camera.rotateZ(pose.roll);

    world.update(frame);
    particles.update(frame);
    lens.render(scene, camera, frame);

    if (motion) {
      if (elapsed !== null) samplePerformance(elapsed);
      schedule();
    }
  }

  return {
    resize(nextWidth, nextHeight) {
      const nextDpr = browser.devicePixelRatio || 1;
      if (nextWidth === width && nextHeight === height && nextDpr === deviceRatio) return;
      width = nextWidth;
      height = nextHeight;
      deviceRatio = nextDpr;
      sizeDirty = true;
      if (width <= 0 || height <= 0) stop();
      else schedule();
    },
    setState(state) {
      if (director) {
        if (!director.setState(state)) return;
      } else {
        director = createDirector(state);
        director.setMotion(motion);
      }
      schedule();
    },
    setOptions(options) {
      if (motion === options.motion && qualityMode === options.quality) return;
      if (motion !== options.motion) {
        motion = options.motion;
        director?.setMotion(motion);
        stop();
      }
      qualityMode = options.quality;
      sizeDirty = true;
      setQuality(qualityMode === "auto" ? adaptiveQuality : qualityMode);
      onFrame?.({ fps: lastFps, quality });
      schedule();
    },
    setVisible(next) {
      if (next === visible) return;
      visible = next;
      if (visible) schedule();
      else stop();
    },
    movePointer(x, y) {
      if (motion) director?.movePointer(x, y);
    },
    orbit(dx, dy) {
      director?.orbit(dx, dy);
      schedule();
    },
    pickSeat(x, y) {
      if (!visible || disposed || width <= 0 || height <= 0 || Math.abs(x) > 1 || Math.abs(y) > 1) return null;
      const scale = lens.sourceScale(x, y);
      const maxHit = MathUtils.clamp(height * 0.048, 14, 27);
      let minimum = maxHit * maxHit;
      let selected: number | null = null;
      for (const [id, anchor] of world.seatAnchors) {
        anchor.getWorldPosition(position).project(camera);
        if (position.z < -1 || position.z > 1) continue;
        const dx = (position.x - x * scale) * width * 0.5;
        const dy = (position.y - y * scale) * height * 0.5;
        const distance = dx * dx + dy * dy;
        if (distance < minimum) {
          minimum = distance;
          selected = id;
        }
      }
      return selected;
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      stop();
      release();
    },
  };
}
