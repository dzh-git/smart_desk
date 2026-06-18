/**
 * Tests for speechTrace.ts — frontend diagnostic trace module (Task 128A).
 *
 * Verifies that getTraceReport always includes wall_clock_offset_ms
 * regardless of whether trace is enabled. Trace recording behavior is
 * tested in the backend tests/test_speech_trace.py (same logic).
 *
 * The module reads import.meta.env.VITE_ENABLE_SPEECH_TRACE at compile
 * time and evaluates _enabled once. Since Vitest caches ES modules,
 * we cannot change _enabled after the first import. We test the shape
 * of the exported data, which is always consistent.
 */
import { describe, it, expect } from "vitest";

describe("speechTrace wall_clock_offset_ms", () => {
  it("getTraceReport always contains wall_clock_offset_ms", async () => {
    const mod = await import("../audio/speechTrace");
    const report = mod.getTraceReport();
    expect(report).toHaveProperty("wall_clock_offset_ms");
    expect(typeof report.wall_clock_offset_ms).toBe("number");
  });

  it("serializeTrace output JSON contains wall_clock_offset_ms", async () => {
    const mod = await import("../audio/speechTrace");
    const jsonStr = mod.serializeTrace();
    const parsed = JSON.parse(jsonStr);
    expect(parsed).toHaveProperty("wall_clock_offset_ms");
    expect(typeof parsed.wall_clock_offset_ms).toBe("number");
  });

  it("wall_clock_offset_ms bridges Date.now and performance.now", async () => {
    const mod = await import("../audio/speechTrace");
    const report = mod.getTraceReport();

    const now = Date.now();
    const perfNow = performance.now();
    const expected = Math.round(now - perfNow);
    // Allow <10ms tolerance for the small capture-to-check gap
    expect(Math.abs(report.wall_clock_offset_ms - expected)).toBeLessThan(10);
  });

  it("serializeTrace output has all expected top-level keys", async () => {
    const mod = await import("../audio/speechTrace");
    const parsed = JSON.parse(mod.serializeTrace());
    expect(parsed).toHaveProperty("recorded_at");
    expect(parsed).toHaveProperty("trace_enabled");
    expect(parsed).toHaveProperty("event_count");
    expect(parsed).toHaveProperty("wall_clock_offset_ms");
    expect(parsed).toHaveProperty("events");
    expect(Array.isArray(parsed.events)).toBe(true);
  });

  it("getTraceReport returns events array even when disabled", async () => {
    const mod = await import("../audio/speechTrace");
    const report = mod.getTraceReport();
    expect(Array.isArray(report.events)).toBe(true);
    expect(report.event_count).toBe(report.events.length);
  });

  it("clearTrace is safe to call regardless of enabled state", async () => {
    const mod = await import("../audio/speechTrace");
    mod.clearTrace();
    mod.clearTrace();
    expect(Array.isArray(mod.getTrace())).toBe(true);
  });

  it("isTraceEnabled returns boolean", async () => {
    const mod = await import("../audio/speechTrace");
    expect(typeof mod.isTraceEnabled()).toBe("boolean");
  });

  it("downloadTraceFile is a function", async () => {
    const mod = await import("../audio/speechTrace");
    expect(typeof mod.downloadTraceFile).toBe("function");
  });
});
