import type { VoteStatistics } from "../api/types";

export type SceneMode = "room" | "agenda" | "vote" | "captions" | "service" | "station" | "display" | "relay" | "identity";
export type ScenePhase = "idle" | "busy" | "live" | "vote" | "speech" | "complete" | "fault";
export type SceneQuality = "auto" | "high" | "medium" | "low";
export type RenderQuality = Exclude<SceneQuality, "auto">;
export type SeatSignal = "vacant" | "assigned" | "ready" | "speaking";

export interface SceneSeat {
  id: number;
  status: SeatSignal;
}

export interface SpatialState {
  mode: SceneMode;
  phase: ScenePhase;
  /** Normalized progress, occupancy or activity coming from the owning view. */
  level?: number;
  seats?: readonly SceneSeat[];
  selectedSeat?: number | null;
  voteShares?: readonly number[];
  /** A stable server-derived value. When it changes the scene acknowledges it once. */
  signal?: string | number | null;
}

export interface SceneTheme {
  accent: string;
  secondary: string;
  shadow: string;
}

export interface SpatialFrame {
  state: SpatialState;
  previousMode: SceneMode;
  /** Progress from previousMode to state.mode. */
  morph: number;
  time: number;
  dt: number;
  pulse: number;
  warp: number;
  dissolve: number;
  pointerX: number;
  pointerY: number;
  motion: boolean;
  quality: RenderQuality;
}

export const MODE_THEME: Record<SceneMode, SceneTheme> = {
  room: { accent: "#bba4ff", secondary: "#ffaf78", shadow: "#18112d" },
  agenda: { accent: "#ffcb82", secondary: "#ff7cab", shadow: "#251425" },
  vote: { accent: "#ffce8a", secondary: "#ea96ee", shadow: "#2b1b23" },
  captions: { accent: "#c4b0ff", secondary: "#79e2ec", shadow: "#1c1c38" },
  service: { accent: "#8ce9bb", secondary: "#7d9fff", shadow: "#0e201d" },
  station: { accent: "#a8bcff", secondary: "#ea8ceb", shadow: "#121a37" },
  display: { accent: "#c0caff", secondary: "#d3a2ff", shadow: "#171630" },
  relay: { accent: "#a3f0f2", secondary: "#9899ff", shadow: "#122327" },
  identity: { accent: "#e6b2eb", secondary: "#8ca6ff", shadow: "#24172c" },
};

export function getTheme({ mode, phase }: SpatialState): SceneTheme {
  const theme = MODE_THEME[mode];
  if (phase === "fault") return { ...theme, accent: "#ffa28b", secondary: "#ba76ae" };
  if (phase === "vote") return { ...theme, accent: "#ffd094", secondary: "#fb82bc" };
  if (phase === "speech") return { ...theme, accent: "#e5b7ff", secondary: "#8ab4ff" };
  if (phase === "complete") return { ...theme, accent: "#b0dcce" };
  return theme;
}

export type SceneChange = "none" | "warp" | "burst" | "dissolve";

export function getVoteShares(stats: VoteStatistics | null | undefined, optionCount = 0) {
  return stats
    ? stats.results.map(({ count }) => stats.total_votes ? count / stats.total_votes : 0)
    : Array.from({ length: optionCount }, () => 0);
}

export function getSceneChange(previous: SpatialState, next: SpatialState): SceneChange {
  if (previous.mode !== next.mode) return "warp";
  if (previous.phase !== next.phase && ["idle", "complete", "fault"].includes(next.phase)) {
    return "dissolve";
  }
  if (previous.phase !== next.phase || previous.selectedSeat !== next.selectedSeat || previous.signal !== next.signal) {
    return "burst";
  }
  const oldShares = previous.voteShares ?? [];
  const newShares = next.voteShares ?? [];
  if (oldShares.length !== newShares.length || newShares.some((value, index) => value !== oldShares[index])) {
    return "burst";
  }
  const oldSeats = previous.seats ?? [];
  const newSeats = next.seats ?? [];
  return newSeats.length !== oldSeats.length
    || newSeats.some((seat, index) => seat.id !== oldSeats[index]?.id || seat.status !== oldSeats[index]?.status)
    ? "burst" : "none";
}

export const SEAT_RADIUS = 2.13;
export const SEAT_HEIGHT = -0.54;

export function seatAngle(id: number): number {
  return Math.PI / 2 + (id - 1) / 9 * Math.PI * 2;
}
