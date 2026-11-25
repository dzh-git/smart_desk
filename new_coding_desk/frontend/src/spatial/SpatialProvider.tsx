import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { SpatialEngine } from "./engine";
import { SpatialContext, type SpatialMetrics, type StageAnchor, type GraphicsStatus } from "./spatialContext";
import { readPreferences, savePreferences, type SpatialPreferences } from "./spatialPreferences";

export function SpatialProvider({ children }: { children: ReactNode }) {
  const [anchor, setAnchor] = useState<StageAnchor | null>(null);
  const [status, setStatus] = useState<GraphicsStatus>("loading");
  const [metrics, setMetrics] = useState<SpatialMetrics | null>(null);
  const [preferences, setPreferences] = useState(readPreferences);
  const [systemReduced, setSystemReduced] = useState(false);
  const anchorRef = useRef<StageAnchor | null>(null);
  const engine = useRef<SpatialEngine | null>(null);
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const start = useRef<(() => void) | null>(null);
  const active = useRef(false);
  const options = useRef({ motion: false, quality: preferences.quality });
  const motion = !preferences.reducedMotion && !systemReduced;

  useEffect(() => {
    const query = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!query) return;
    const update = () => setSystemReduced(query.matches);
    update();
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);

  useEffect(() => {
    options.current = { motion, quality: preferences.quality };
    engine.current?.setOptions(options.current);
    savePreferences(preferences);
  }, [motion, preferences]);

  const register = useCallback((next: StageAnchor) => {
    anchorRef.current = next;
    setAnchor(next);
    return () => {
      if (anchorRef.current !== next) return;
      anchorRef.current = null;
      setAnchor(null);
    };
  }, []);

  const setScene = useCallback((owner: StageAnchor) => {
    if (anchorRef.current === owner) engine.current?.setState(owner.state);
  }, []);

  useEffect(() => {
    if (typeof window.WebGL2RenderingContext === "undefined") {
      setStatus("fallback");
      return;
    }
    const surface = document.createElement("canvas");
    surface.className = "spatial-canvas";
    surface.setAttribute("aria-hidden", "true");
    canvas.current = surface;
    let disposed = false;
    let loading = false;

    const create = async () => {
      if (disposed || loading || engine.current || !anchorRef.current) return;
      loading = true;
      try {
        const { createSpatialEngine } = await import("./engine");
        if (disposed) return;
        const view = createSpatialEngine(surface, (frame) => {
          if (!disposed) setMetrics(frame);
        });
        engine.current = view;
        view.setOptions(options.current);
        const target = anchorRef.current;
        if (target) {
          target.host.appendChild(surface);
          view.resize(target.host.clientWidth, target.host.clientHeight);
          view.setState(target.state);
        }
        view.setVisible(active.current && Boolean(target) && !document.hidden);
        setStatus("ready");
      } catch {
        if (!disposed) setStatus("fallback");
      } finally {
        loading = false;
      }
    };

    const lost = (event: Event) => {
      event.preventDefault();
      engine.current?.dispose();
      engine.current = null;
      setMetrics(null);
      setStatus("fallback");
    };
    const restored = () => { void create(); };
    surface.addEventListener("webglcontextlost", lost);
    surface.addEventListener("webglcontextrestored", restored);
    start.current = () => { void create(); };
    return () => {
      disposed = true;
      surface.removeEventListener("webglcontextlost", lost);
      surface.removeEventListener("webglcontextrestored", restored);
      engine.current?.dispose();
      engine.current = null;
      surface.remove();
      canvas.current = null;
      start.current = null;
    };
  }, []);

  useEffect(() => {
    if (!anchor) {
      engine.current?.setVisible(false);
      return;
    }

    const { host } = anchor;
    const surface = canvas.current;
    if (surface && surface.parentElement !== host) host.appendChild(surface);
    let visible = true;

    const refresh = () => {
      active.current = visible && !document.hidden && host.isConnected;
      if (active.current) engine.current?.resize(host.clientWidth, host.clientHeight);
      engine.current?.setVisible(active.current);
    };

    const resize = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(refresh);
    const intersection = typeof IntersectionObserver === "undefined" ? null : new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      refresh();
    });
    resize?.observe(host);
    intersection?.observe(host);
    window.addEventListener("resize", refresh);
    document.addEventListener("visibilitychange", refresh);
    engine.current?.setState(anchor.state);
    refresh();
    start.current?.();

    return () => {
      active.current = false;
      engine.current?.setVisible(false);
      resize?.disconnect();
      intersection?.disconnect();
      window.removeEventListener("resize", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [anchor]);

  const controller = useMemo(() => ({
    register,
    setScene,
    pointer: (x: number, y: number) => engine.current?.movePointer(x, y),
    orbit: (dx: number, dy: number) => engine.current?.orbit(dx, dy),
    pickSeat: (x: number, y: number) => engine.current?.pickSeat(x, y) ?? null,
  }), [register, setScene]);

  const value = useMemo(() => ({
    ...controller,
    status,
    metrics,
    preferences,
    setPreferences: (next: SpatialPreferences) => setPreferences(next),
    systemReduced,
  }), [controller, metrics, preferences, status, systemReduced]);

  return <SpatialContext.Provider value={value}>{children}</SpatialContext.Provider>;
}
