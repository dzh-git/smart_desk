import { AdditiveBlending, Color, ShaderMaterial } from "three";

const palette = /* glsl */ `
  uniform vec3 uAccent;
  uniform vec3 uSecondary;
  varying float vEnergy;
  varying float vTone;
`;

export function createPointMaterial() {
  return new ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: AdditiveBlending,
    toneMapped: false,
    uniforms: {
      uAccent: { value: new Color() },
      uSecondary: { value: new Color() },
      uPixelRatio: { value: 1 },
    },
    vertexShader: /* glsl */ `
      uniform float uPixelRatio;
      attribute float aEnergy;
      attribute float aSeed;
      attribute float aDrift;
      varying float vEnergy;
      varying float vTone;

      void main() {
        vec4 viewPosition = modelViewMatrix * vec4(position, 1.0);
        float perspective = clamp(6.4 / max(1.0, -viewPosition.z), 0.76, 1.32);
        float size = mix(1.7 + aSeed * aSeed * 1.28, 1.55, aDrift);
        gl_PointSize = size * perspective * uPixelRatio;
        gl_Position = projectionMatrix * viewPosition;
        vEnergy = aEnergy;
        vTone = smoothstep(0.28, 0.95, aSeed);
      }
    `,
    fragmentShader: /* glsl */ `
      ${palette}

      void main() {
        float radius = length(gl_PointCoord - 0.5);
        float core = 1.0 - smoothstep(0.06, 0.42, radius);
        float halo = 1.0 - smoothstep(0.24, 0.5, radius);
        gl_FragColor = vec4(mix(uAccent, uSecondary, vTone), vEnergy * (core * 0.77 + halo * 0.23));
        #include <colorspace_fragment>
      }
    `,
  });
}

export function createTrailMaterial() {
  return new ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: AdditiveBlending,
    toneMapped: false,
    uniforms: {
      uAccent: { value: new Color() },
      uSecondary: { value: new Color() },
    },
    vertexShader: /* glsl */ `
      attribute float aEnergy;
      attribute float aSeed;
      varying float vEnergy;
      varying float vTone;

      void main() {
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        vEnergy = aEnergy;
        vTone = aSeed;
      }
    `,
    fragmentShader: /* glsl */ `
      ${palette}

      void main() {
        gl_FragColor = vec4(mix(uAccent, uSecondary, vTone), vEnergy);
        #include <colorspace_fragment>
      }
    `,
  });
}
