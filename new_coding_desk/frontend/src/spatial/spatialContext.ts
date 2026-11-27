import { createContext } from "react";
import type { RenderQuality, SpatialState } from "./sceneState";
import type { SpatialPreferences } from "./spatialPreferences";

export interface StageAnchor {
  host: HTMLElement;
  state: SpatialState;
}

export interface SpatialMetrics {
  fps: number;
  quality: RenderQuality;
}

export type GraphicsStatus = "loading" | "ready" | "fallback";

interface SpatialControls {
  register(anchor: StageAnchor): () => void;
  setScene(anchor: StageAnchor): void;
  pointer(x: number, y: number): void;
  orbit(dx: number, dy: number): void;
  impulse(x?: number, y?: number): void;
  pickSeat(x: number, y: number): number | null;
  status: GraphicsStatus;
  metrics: SpatialMetrics | null;
  preferences: SpatialPreferences;
  setPreferences(preferences: SpatialPreferences): void;
  systemReduced: boolean;
}

export const SpatialContext = createContext<SpatialControls | null>(null);
