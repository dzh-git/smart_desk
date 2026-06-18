// ─── Agenda State Helper ───────────────────────────────────────────────────────
// Pure functions to derive current agenda, progress, and flow-done status from
// an Agenda[].  No React hooks, no side effects — use anywhere.
//
// All functions accept the raw Agenda[] from the API (already sorted by
// sort_order on the backend) and return derived state.

import type { Agenda } from "../api/types";

// ── Types ───────────────────────────────────────────────────────────────────

export interface AgendaProgress {
  total: number;
  completed: number;
  skipped: number;
  active: number;
  pending: number;
  current_index: number | null;
}

export interface AgendaDerivedState {
  current: Agenda | null;
  progress: AgendaProgress;
  isFlowDone: boolean;
}

// ── Public Helpers ─────────────────────────────────────────────────────────

/** Derive the full agenda state object (current + progress + flow-done). */
export function deriveAgendaState(agendas: Agenda[]): AgendaDerivedState {
  const current = getCurrentAgenda(agendas);
  const progress = getAgendaProgress(agendas);
  const isFlowDone = isAgendaFlowDone(agendas);
  return { current, progress, isFlowDone };
}

/**
 * Return the single active agenda item, or null if none is active.
 * There should never be more than one active agenda per meeting (enforced
 * by the backend), but if there is, the first one found is returned.
 */
export function getCurrentAgenda(agendas: Agenda[]): Agenda | null {
  return agendas.find((a) => a.status === "active") ?? null;
}

/**
 * Compute progress counters from the agenda list.
 *
 * - total: agendas.length
 * - completed/skipped/active/pending: count by status
 * - current_index: 1-based index of the active agenda (by sort_order),
 *   or null when no agenda is active
 */
export function getAgendaProgress(agendas: Agenda[]): AgendaProgress {
  const sorted = [...agendas].sort(
    (a, b) => (a.sort_order ?? a.id) - (b.sort_order ?? b.id),
  );

  let completed = 0;
  let skipped = 0;
  let active = 0;
  let pending = 0;
  let currentIndex: number | null = null;

  sorted.forEach((a, i) => {
    switch (a.status) {
      case "completed":
        completed++;
        break;
      case "skipped":
        skipped++;
        break;
      case "active":
        active++;
        currentIndex = i + 1; // 1-based
        break;
      case "pending":
        pending++;
        break;
    }
  });

  return {
    total: sorted.length,
    completed,
    skipped,
    active,
    pending,
    current_index: currentIndex,
  };
}

/**
 * Return true when all agenda items have been processed (no active or
 * pending items remain) AND there is at least one agenda item.
 */
export function isAgendaFlowDone(agendas: Agenda[]): boolean {
  if (agendas.length === 0) return false;
  const progress = getAgendaProgress(agendas);
  return progress.active === 0 && progress.pending === 0;
}
