import {
  BufferGeometry, Camera, Color, Float32BufferAttribute, HalfFloatType, Mesh, NoBlending,
  Scene, ShaderMaterial, UnsignedByteType, Vector2, WebGLRenderTarget,
  type WebGLRenderer,
} from "three";
import { getTheme, type RenderQuality, type SpatialFrame } from "./sceneState";

const screenVertex = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = position.xy * 0.5 + 0.5;
  gl_Position = vec4(position.xy, 0.0, 1.0);
}`;

const highlightFragment = /* glsl */ `
uniform sampler2D uImage;
uniform float uThreshold;
varying vec2 vUv;
void main() {
  vec3 color = texture2D(uImage, vUv).rgb;
  float brightness = max(max(color.r, color.g), color.b);
  gl_FragColor = vec4(color * smoothstep(uThreshold, uThreshold + 0.55, brightness), 1.0);
}`;

const blurFragment = /* glsl */ `
uniform sampler2D uImage;
uniform vec2 uStep;
varying vec2 vUv;
void main() {
  vec3 color = texture2D(uImage, vUv).rgb * 0.227027;
  color += (texture2D(uImage, vUv + uStep * 1.384615).rgb
    + texture2D(uImage, vUv - uStep * 1.384615).rgb) * 0.316216;
  color += (texture2D(uImage, vUv + uStep * 3.230769).rgb
    + texture2D(uImage, vUv - uStep * 3.230769).rgb) * 0.070270;
  gl_FragColor = vec4(color, 1.0);
}`;

const BASE_CURVATURE = 0.008;
const WARP_CURVATURE = 0.19;
const CURVATURE_MARGIN = 0.33;

const compositeFragment = /* glsl */ `
uniform sampler2D uImage;
uniform sampler2D uGlow;
uniform float uAspect;
uniform float uWarp;
uniform float uDissolve;
uniform float uTime;
uniform float uBloomStrength;
uniform float uTrails;
uniform vec3 uTint;
varying vec2 vUv;

vec3 filmic(vec3 x) {
  return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
}

vec3 displayColor(vec3 x) {
  return mix(x * 12.92, 1.055 * pow(x, vec3(1.0 / 2.4)) - 0.055, step(0.0031308, x));
}

void main() {
  vec2 delta = vUv - 0.5;
  vec2 lensDelta = vec2(delta.x * uAspect, delta.y);
  float radiusSquared = dot(lensDelta, lensDelta);
  float edge = smoothstep(0.012, 0.46, radiusSquared);
  float margin = 1.0 - smoothstep(${CURVATURE_MARGIN}, 0.5, max(abs(delta.x), abs(delta.y)));
  vec2 uv = vUv + delta * radiusSquared * (${BASE_CURVATURE} + uWarp * ${WARP_CURVATURE}) * margin;
  vec4 image = texture2D(uImage, uv);
  vec3 color = image.rgb;
  float alpha = image.a;
  if (uWarp > 0.015) {
    vec2 dispersion = delta * edge * 0.04 * uWarp;
    vec4 red = texture2D(uImage, uv - dispersion);
    vec4 blue = texture2D(uImage, uv + dispersion);
    color = vec3(red.r, image.g, blue.b);
    alpha = max(alpha, max(red.a, blue.a) * 0.65);
  }

  if (uTrails > 0.0 && uWarp > 0.015) {
    vec2 ray = delta * uWarp * (0.035 + edge * 0.155);
    vec4 inner = texture2D(uImage, uv - ray * 0.54);
    vec4 outer = texture2D(uImage, uv + ray);
    float blend = uWarp * uTrails * (0.22 + edge * 0.56);
    color = mix(color, inner.rgb * 0.56 + outer.rgb * 0.44, blend);
    alpha = mix(alpha, inner.a * 0.56 + outer.a * 0.44, blend);
  }

  if (uBloomStrength > 0.0) {
    vec3 glow = texture2D(uGlow, uv).rgb;
    color += glow * uBloomStrength * (1.0 + uWarp * 0.42);
  }

  float luminance = max(max(color.r, color.g), color.b);
  if (uDissolve > 0.015) {
    float radialBand = 1.0 - smoothstep(0.015, 0.17, abs(sqrt(radiusSquared) - 0.4 - sin(uTime * 5.0) * 0.11));
    color = color * (1.0 - uDissolve * edge * 0.17)
      + uTint * radialBand * uDissolve * min(luminance, 1.2) * 0.21;
  }
  float vignette = 1.0 - smoothstep(0.1, 1.05, radiusSquared) * (0.17 + uWarp * 0.22);
  alpha = max(alpha, min(0.92, luminance * 0.75));
  vec3 mapped = filmic(max(vec3(0.0), color * vignette * 0.87) / max(0.001, alpha));
  gl_FragColor = vec4(displayColor(mapped) * alpha, alpha);
}`;

function material(fragmentShader: string, uniforms: ShaderMaterial["uniforms"]) {
  return new ShaderMaterial({
    vertexShader: screenVertex,
    fragmentShader,
    uniforms,
    blending: NoBlending,
    depthTest: false,
    depthWrite: false,
    toneMapped: false,
  });
}

export function createLens(renderer: WebGLRenderer, gl: WebGL2RenderingContext) {
  const hdr = renderer.extensions.has("EXT_color_buffer_float");
  const colorSamples: Int32Array = gl.getInternalformatParameter(
    gl.RENDERBUFFER, hdr ? gl.RGBA16F : gl.RGBA8, gl.SAMPLES,
  );
  const depthSamples: Int32Array = gl.getInternalformatParameter(gl.RENDERBUFFER, gl.DEPTH_COMPONENT24, gl.SAMPLES);
  const highSamples = colorSamples?.includes(2) && depthSamples?.includes(2) ? 2 : 0;
  const options = { type: hdr ? HalfFloatType : UnsignedByteType };
  const image = new WebGLRenderTarget(1, 1, options);
  const highlights = new WebGLRenderTarget(1, 1, { ...options, depthBuffer: false });
  const blur = new WebGLRenderTarget(1, 1, { ...options, depthBuffer: false });
  const screen = new Scene();
  const screenCamera = new Camera();
  const geometry = new BufferGeometry();
  geometry.setAttribute("position", new Float32BufferAttribute([-1, -1, 0, 3, -1, 0, -1, 3, 0], 3));
  const highlightUniforms = { uImage: { value: image.texture }, uThreshold: { value: hdr ? 0.68 : 0.4 } };
  const blurUniforms = { uImage: { value: highlights.texture }, uStep: { value: new Vector2() } };
  const compositeUniforms = {
    uImage: { value: image.texture },
    uGlow: { value: highlights.texture },
    uAspect: { value: 1 },
    uWarp: { value: 0 },
    uDissolve: { value: 0 },
    uTime: { value: 0 },
    uBloomStrength: { value: 0 },
    uTrails: { value: 0 },
    uTint: { value: new Color() },
  };
  const highlightPass = material(highlightFragment, highlightUniforms);
  const blurPass = material(blurFragment, blurUniforms);
  const compositePass = material(compositeFragment, compositeUniforms);
  const triangle = new Mesh(geometry, compositePass);
  triangle.frustumCulled = false;
  screen.add(triangle);
  let quality: RenderQuality = "high";

  function pass(effect: ShaderMaterial, target: WebGLRenderTarget | null) {
    triangle.material = effect;
    renderer.setRenderTarget(target);
    renderer.render(screen, screenCamera);
  }

  return {
    setSize(width: number, height: number, nextQuality: RenderQuality) {
      quality = nextQuality;
      const samples = quality === "high" ? highSamples : 0;
      if (image.samples !== samples) {
        image.dispose();
        image.samples = samples;
      }
      image.setSize(width, height);
      compositeUniforms.uAspect.value = Math.min(1.85, width / height);
      const scale = quality === "high" ? 0.37 : 0.27;
      const glowWidth = quality === "low" ? 1 : Math.max(1, Math.floor(width * scale));
      const glowHeight = quality === "low" ? 1 : Math.max(1, Math.floor(height * scale));
      highlights.setSize(glowWidth, glowHeight);
      blur.setSize(glowWidth, glowHeight);
      compositeUniforms.uBloomStrength.value = quality === "high" ? 0.62 : quality === "medium" ? 0.53 : 0;
      compositeUniforms.uTrails.value = quality === "high" ? 1 : quality === "medium" ? 0.8 : 0;
    },
    render(scene: Scene, camera: Camera, frame: SpatialFrame) {
      renderer.setRenderTarget(image);
      renderer.render(scene, camera);
      if (quality !== "low") {
        pass(highlightPass, highlights);
        const radius = 1.4 + frame.warp * 1.3 + frame.pulse * 0.35;
        blurUniforms.uImage.value = highlights.texture;
        blurUniforms.uStep.value.set(radius / highlights.width, 0);
        pass(blurPass, blur);
        blurUniforms.uImage.value = blur.texture;
        blurUniforms.uStep.value.set(0, radius / highlights.height);
        pass(blurPass, highlights);
      }

      compositeUniforms.uWarp.value = frame.warp;
      compositeUniforms.uDissolve.value = frame.dissolve;
      compositeUniforms.uTime.value = frame.time;
      compositeUniforms.uTint.value.set(getTheme(frame.state).accent);
      pass(compositePass, null);
    },
    sourceScale(x: number, y: number) {
      const lensX = x * compositeUniforms.uAspect.value;
      const radiusSquared = (lensX * lensX + y * y) * 0.25;
      const edge = Math.min(1, Math.max(0, (Math.max(Math.abs(x), Math.abs(y)) * 0.5 - CURVATURE_MARGIN) / (0.5 - CURVATURE_MARGIN)));
      const margin = 1 - edge * edge * (3 - 2 * edge);
      return 1 + radiusSquared * (BASE_CURVATURE + compositeUniforms.uWarp.value * WARP_CURVATURE) * margin;
    },
    dispose() {
      geometry.dispose();
      highlightPass.dispose();
      blurPass.dispose();
      compositePass.dispose();
      image.dispose();
      highlights.dispose();
      blur.dispose();
    },
  };
}
