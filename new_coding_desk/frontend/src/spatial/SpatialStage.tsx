import {
  useContext, useLayoutEffect, useRef,
  type CSSProperties, type ReactNode, type PointerEvent,
} from "react";
import { Aperture, SlidersHorizontal } from "lucide-react";
import { getTheme, type SceneQuality, type SceneMode, type SpatialState } from "./sceneState";
import { SpatialContext, type StageAnchor } from "./spatialContext";

const SUBJECTS: Record<SceneMode, string> = {
  room: "九席智能会议桌",
  agenda: "会议议程",
  vote: "投票分布",
  captions: "双语字幕",
  service: "茶水服务",
  station: "参会席终端",
  display: "会议演示屏",
  relay: "主机到大屏",
  identity: "席位身份验证",
};

const QUALITY_LABELS: Record<SceneQuality, string> = {
  auto: "自动", high: "高", medium: "中", low: "低",
};

interface SpatialStageProps {
  state: SpatialState;
  className?: string;
  children?: ReactNode;
  onSelectSeat?: (seatId: number) => void;
  showTitle?: boolean;
}

export function SpatialStage({ state, className = "", children, onSelectSeat, showTitle = true }: SpatialStageProps) {
  const spatial = useContext(SpatialContext);
  const viewport = useRef<HTMLDivElement>(null);
  const current = useRef<StageAnchor | null>(null);
  const initialState = useRef(state);
  const drag = useRef<{ id: number; x: number; y: number; travelled: number } | null>(null);
  const register = spatial?.register;
  const setScene = spatial?.setScene;
  const theme = getTheme(state);
  const status = spatial?.status ?? "fallback";
  const motion = spatial && !spatial.systemReduced && !spatial.preferences.reducedMotion;

  useLayoutEffect(() => {
    const host = viewport.current;
    if (!register || !host) return;
    const anchor = { host, state: initialState.current };
    current.current = anchor;
    const detach = register(anchor);
    return () => {
      detach();
      current.current = null;
    };
  }, [register]);

  useLayoutEffect(() => {
    if (current.current) {
      current.current.state = state;
      setScene?.(current.current);
    }
  }, [state, setScene]);

  function pointerPosition(event: PointerEvent<HTMLDivElement>): [number, number] {
    const box = event.currentTarget.getBoundingClientRect();
    return [2 * (event.clientX - box.left) / box.width - 1, 1 - 2 * (event.clientY - box.top) / box.height];
  }

  function pointerDown(event: PointerEvent<HTMLDivElement>) {
    if (status !== "ready" || event.button !== 0 || !event.isPrimary) return;
    drag.current = { id: event.pointerId, x: event.clientX, y: event.clientY, travelled: 0 };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  function pointerMove(event: PointerEvent<HTMLDivElement>) {
    if (!spatial || status !== "ready") return;
    spatial.pointer(...pointerPosition(event));
    const pointer = drag.current;
    if (pointer?.id !== event.pointerId) return;
    const dx = event.clientX - pointer.x;
    const dy = event.clientY - pointer.y;
    pointer.travelled += Math.hypot(dx, dy);
    pointer.x = event.clientX;
    pointer.y = event.clientY;
    if (pointer.travelled > 4) spatial.orbit(dx, dy);
  }

  function pointerUp(event: PointerEvent<HTMLDivElement>) {
    if (!spatial || drag.current?.id !== event.pointerId) return;
    if (drag.current.travelled <= 4) {
      const point = pointerPosition(event);
      const seat = onSelectSeat ? spatial.pickSeat(...point) : null;
      if (seat != null) onSelectSeat?.(seat);
      else spatial.impulse(...point);
    }
    drag.current = null;
  }

  return (
    <section
      className={`spatial-stage ${className}`}
      style={{ "--scene-accent": theme.accent, "--scene-secondary": theme.secondary, "--scene-shadow": theme.shadow } as CSSProperties}
      data-testid="spatial-stage"
      data-mode={state.mode}
      data-phase={state.phase}
      data-renderer={status === "ready" ? "webgl2" : status}
      aria-label={SUBJECTS[state.mode]}
    >
      <div
        ref={viewport}
        className="spatial-viewport"
        tabIndex={status === "ready" ? 0 : undefined}
        aria-label={status === "ready" ? "三维视角，拖动或使用方向键旋转，按回车聚焦" : undefined}
        onPointerDown={pointerDown}
        onPointerMove={pointerMove}
        onPointerUp={pointerUp}
        onPointerCancel={() => { drag.current = null; }}
        onPointerLeave={() => spatial?.pointer(0, 0)}
        onKeyDown={(event) => {
          if (!spatial) return;
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            spatial.impulse();
            return;
          }
          const directions: Record<string, [number, number]> = {
            ArrowLeft: [-28, 0], ArrowRight: [28, 0], ArrowUp: [0, -22], ArrowDown: [0, 22],
          };
          const direction = directions[event.key];
          if (direction) {
            event.preventDefault();
            spatial.orbit(...direction);
          }
        }}
      />
      <div className="spatial-stage__top">
        {showTitle && <div className="spatial-stage__label">
          <Aperture size={15} aria-hidden="true" />
          <span>{SUBJECTS[state.mode]}</span>
        </div>}
        {spatial && status === "ready" && (
          <details className={`spatial-settings ${showTitle ? "" : "ml-auto"}`}>
            <summary><SlidersHorizontal size={14} aria-hidden="true" />画质</summary>
            <div className="spatial-settings__menu">
              <label>
                渲染质量
                <select value={spatial.preferences.quality} onChange={(event) => spatial.setPreferences({
                  ...spatial.preferences, quality: event.target.value as SceneQuality,
                })}>
                  {Object.entries(QUALITY_LABELS).map(([value, label]) => (
                    <option value={value} key={value}>{label}</option>
                  ))}
                </select>
              </label>
              <label className="spatial-settings__motion">
                <input type="checkbox" checked={!motion} disabled={spatial.systemReduced} onChange={(event) => spatial.setPreferences({
                  ...spatial.preferences, reducedMotion: event.target.checked,
                })} />
                减少动效
              </label>
              {spatial.systemReduced && <span>遵循系统减少动效设置</span>}
            </div>
          </details>
        )}
      </div>
      {children && <div className="spatial-stage__content">{children}</div>}
    </section>
  );
}
