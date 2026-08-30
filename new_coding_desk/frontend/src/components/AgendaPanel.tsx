import { useState, useCallback } from "react";
import {
  CheckCircle2,
  SkipForward,
  Play,
  Trash2,
  Plus,
  Loader2,
  AlertCircle,
  ArrowRight,
} from "lucide-react";
import { PanelCard, ActionButton } from "./shared";
import type { Agenda } from "../api/types";
import {
  deriveAgendaState,
} from "../utils/agendaState";
const DEFAULT_AGENDA_TITLE =
  "会议开场与议题确认 / Opening and Agenda Confirmation";


// ── Props ──────────────────────────────────────────────────────────────────

interface AgendaCommandCenterProps {
  agendas: Agenda[];
  /** Called when user confirms "Set Current" for a pending/skipped agenda. */
  onSetCurrent: (agendaId: number) => Promise<void>;
  /** Called when user confirms Advance. */
  onAdvance: () => Promise<void>;
  /** Called when user confirms Complete. */
  onComplete: (agendaId: number) => Promise<void>;
  /** Called when user confirms Skip (with confirmation). */
  onSkip: (agendaId: number) => Promise<void>;
  /** Called to delete an agenda item. */
  onDelete: (agendaId: number) => Promise<void>;
  /** Called to add a new agenda item. */
  onAdd: (title: string) => Promise<void>;
  /** True while any agenda write operation is in flight. */
  busy: boolean;
  /** True when the meeting is ended — all controls become read-only. */
  readOnly: boolean;
  /** Human-readable error message from last operation, or null. */
  actionError: string | null;
  /** Call to clear the action error. */
  onClearError: () => void;
  /** Whether this is an active meeting (controls enabled). */
  meetingActive: boolean;
}

// ── Component ──────────────────────────────────────────────────────────────

export function AgendaCommandCenter({
  agendas,
  onSetCurrent,
  onAdvance,
  onComplete,
  onSkip,
  onDelete,
  onAdd,
  busy,
  readOnly,
  actionError: _actionError,
  onClearError: _onClearError,
  meetingActive,
}: AgendaCommandCenterProps) {
  // ── Derived state ──────────────────────────────────────────────────────
  const sorted = [...agendas].sort(
    (a, b) => (a.sort_order ?? a.id) - (b.sort_order ?? b.id),
  );
  const state = deriveAgendaState(sorted);
  const progress = state.progress;
  const current = state.current;
  const isFlowDone = state.isFlowDone;

  // ── Local UI state ─────────────────────────────────────────────────────
  const [previewId, setPreviewId] = useState<number | null>(null);
  const [newTitle, setNewTitle] = useState(DEFAULT_AGENDA_TITLE);
  const [addBusy, setAddBusy] = useState(false);

  // Reset preview when agendas change (e.g. after refresh)
  // Only keep preview if the item still exists
  const previewItem: Agenda | null =
    previewId != null ? sorted.find((a) => a.id === previewId) ?? null : null;

  const handlePreview = useCallback((id: number) => {
    setPreviewId((prev) => (prev === id ? null : id));
  }, []);

  const handleAdd = useCallback(async () => {
    const title = newTitle.trim();
    if (!title) return;
    setAddBusy(true);
    try {
      await onAdd(title);
      setNewTitle(DEFAULT_AGENDA_TITLE);
    } finally {
      setAddBusy(false);
    }
  }, [newTitle, onAdd]);

  // Determine which agenda to show in the center panel:
  // 1. If there's a preview, show that (even if it's the current active)
  // 2. Otherwise show the current active
  // 3. If neither, show empty state
  const centerAgenda = previewItem ?? current;

  // Check if previewed agenda is the currently active one
  const isPreviewActive = previewItem != null && current != null && previewItem.id === current.id;
  const hasActiveAgenda = current != null;

  // ── Status config ──────────────────────────────────────────────────────
  const statusConfig: Record<
    string,
    { labelCn: string; labelEn: string; dot: string; text: string; bg: string }
  > = {
    pending: {
      labelCn: "待处理",
      labelEn: "PENDING",
      dot: "bg-techMuted",
      text: "text-techMuted",
      bg: "bg-techCardSoft",
    },
    active: {
      labelCn: "进行中",
      labelEn: "ACTIVE",
      dot: "bg-techCyan",
      text: "text-techCyan",
      bg: "bg-techCyan/5",
    },
    completed: {
      labelCn: "已完成",
      labelEn: "DONE",
      dot: "bg-techGreen",
      text: "text-techGreen",
      bg: "bg-techGreen/5",
    },
    skipped: {
      labelCn: "已跳过",
      labelEn: "SKIPPED",
      dot: "bg-techAmber",
      text: "text-techAmber",
      bg: "bg-techAmber/5",
    },
  };

  // ── Timeline item click handler ────────────────────────────────────────
  const handleTimelineClick = useCallback(
    (id: number) => {
      if (readOnly) return;
      handlePreview(id);
    },
    [readOnly, handlePreview],
  );

  // ── Render helper: timeline item ───────────────────────────────────────
  const renderTimelineItem = (item: Agenda) => {
    const cfg = statusConfig[item.status] ?? statusConfig.pending;
    const isSelected = previewId === item.id;
    const isActiveItem = item.status === "active";

    return (
      <button
        key={item.id}
        onClick={() => handleTimelineClick(item.id)}
        disabled={readOnly}
        className={`w-full text-left rounded-lg px-3 py-2.5 transition-all duration-150 border ${
          isSelected
            ? "border-techCyan/50 bg-techCyan/10"
            : isActiveItem
              ? "border-techCyan/30 bg-techCyan/5"
              : "border-transparent hover:bg-techCardSoft"
        } ${
          readOnly ? "cursor-default" : "cursor-pointer"
        } disabled:opacity-60`}
      >
        <div className="flex items-center gap-2.5">
          {/* Status dot */}
          <div className="flex-shrink-0 relative">
            <div className={`w-2.5 h-2.5 rounded-full ${cfg.dot}`} />
            {item.status === "active" && (
              <span className="absolute inset-0 rounded-full bg-techCyan/40 animate-ping" />
            )}
          </div>
          {/* Title */}
          <div className="min-w-0 flex-1">
            <p
              className={`text-sm font-medium truncate ${
                isActiveItem ? "text-techCyan" : "text-techText"
              }`}
            >
              {item.title}
            </p>
          </div>
          {/* Status label */}
          <span
            className={`text-[0.6rem] font-mono uppercase tracking-wider flex-shrink-0 ${cfg.text}`}
          >
            {cfg.labelEn}
          </span>
        </div>
      </button>
    );
  };

  // ── Render helper: status badge ────────────────────────────────────────
  const renderStatusBadge = (status: string) => {
    const cfg = statusConfig[status] ?? statusConfig.pending;
    return (
      <span
        className={`inline-flex items-center gap-1.5 text-xs font-medium border border-current/30 rounded-full px-2.5 py-1 ${cfg.bg} ${cfg.text}`}
      >
        <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
        {cfg.labelCn}
        <span className="text-[0.6rem] font-mono uppercase tracking-wider opacity-60">
          {cfg.labelEn}
        </span>
      </span>
    );
  };

  // ── Determine if SetCurrent should be available ────────────────────────
  const canSetCurrent =
    !readOnly &&
    meetingActive &&
    previewItem != null &&
    (previewItem.status === "pending" || previewItem.status === "skipped") &&
    !busy;

  // ── Determine action button availability ───────────────────────────────
  const canAdvance = !readOnly && meetingActive && hasActiveAgenda && !busy;
  const canComplete = !readOnly && meetingActive && hasActiveAgenda && !busy;
  const canSkip = !readOnly && meetingActive && hasActiveAgenda && !busy;
  const canDelete = (item: Agenda) =>
    !readOnly && meetingActive && item.status !== "active" && !busy;

  return (
    <PanelCard
      titleCn="议程控制台"
      titleEn="AGENDA COMMAND"
      variant={isFlowDone ? "success" : meetingActive ? "active" : "default"}
      className="w-full"
    >
      {/* ── Flow Done Banner ──────────────────────────────────────────────── */}
      {isFlowDone && (
        <div className="mb-4 rounded-lg border border-techGreen/30 bg-techGreen/5 px-4 py-3 text-center">
          <p className="text-sm font-semibold text-techGreen">
            所有议题已处理
          </p>
          <p className="text-[0.65rem] font-mono uppercase tracking-wider text-techGreen/70 mt-0.5">
            ALL TOPICS PROCESSED
          </p>
        </div>
      )}

      {/* ── Three-column layout ───────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* ─── LEFT: Timeline ─────────────────────────────────────────────── */}
        <div className="lg:col-span-4 space-y-1">
          <div className="flex items-center justify-between mb-2">
            <span className="inline-flex items-baseline gap-1.5">
              <span className="text-xs font-semibold text-techText">
                议程时间线
              </span>
              <span className="text-[0.6rem] font-mono uppercase tracking-wider text-techMuted">
                AGENDA TIMELINE
              </span>
            </span>
            <span className="text-[0.6rem] font-mono text-techMuted">
              {progress.completed + progress.skipped}/{progress.total}
            </span>
          </div>

          {sorted.length === 0 ? (
            <div className="py-6 text-center">
              <p className="text-xs text-techMuted">
                暂无议题 / NO TOPICS
              </p>
            </div>
          ) : (
            <div className="space-y-1 max-h-80 overflow-y-auto pr-1">
              {sorted.map(renderTimelineItem)}
            </div>
          )}
        </div>

        {/* ─── CENTER: Current Topic / Preview ─────────────────────────────── */}
        <div className="lg:col-span-4 border-l border-r border-techBorder/50 px-4">
          <div className="flex items-center justify-between mb-3">
            <span className="inline-flex items-baseline gap-1.5">
              <span className="text-xs font-semibold text-techText">
                {previewItem ? "议题预览" : "当前议题"}
              </span>
              <span className="text-[0.6rem] font-mono uppercase tracking-wider text-techMuted">
                {previewItem ? "TOPIC PREVIEW" : "CURRENT TOPIC"}
              </span>
            </span>
          </div>

          {centerAgenda ? (
            <div className="space-y-3">
              {/* Preview indicator */}
              {previewItem && !isPreviewActive && (
                <div className="rounded-md border border-techCyan/30 bg-techCyan/5 px-3 py-1.5">
                  <p className="text-[0.6rem] font-mono text-techCyan flex items-center gap-1">
                    <AlertCircle size={10} />
                    预览中 - 尚未切换 / PREVIEW ONLY
                  </p>
                </div>
              )}

              {/* Topic title */}
              <div>
                <p className="text-sm font-semibold text-techText leading-snug">
                  {centerAgenda.title}
                </p>
                <p className="text-xs text-techMuted mt-0.5">
                  ID: {centerAgenda.id} · 排序: {centerAgenda.sort_order}
                </p>
              </div>

              {/* Status badge */}
              <div>{renderStatusBadge(centerAgenda.status)}</div>

              {/* Timestamps */}
              <div className="space-y-1 text-xs text-techMuted">
                {centerAgenda.started_at && (
                  <p>
                    开始时间 / STARTED:{" "}
                    {new Date(centerAgenda.started_at).toLocaleTimeString()}
                  </p>
                )}
                {centerAgenda.completed_at && (
                  <p>
                    完成时间 / DONE:{" "}
                    {new Date(centerAgenda.completed_at).toLocaleTimeString()}
                  </p>
                )}
                {centerAgenda.skipped_at && (
                  <p>
                    跳过时间 / SKIPPED:{" "}
                    {new Date(centerAgenda.skipped_at).toLocaleTimeString()}
                  </p>
                )}
              </div>

              {/* Delete button for non-active items */}
              {previewItem && canDelete(previewItem) && (
                <div className="pt-1">
                  <ActionButton
                    variant="ghost"
                    size="sm"
                    icon={<Trash2 size={12} />}
                    onClick={() => onDelete(previewItem.id)}
                    disabled={busy}
                  >
                    删除 / DELETE
                  </ActionButton>
                </div>
              )}

              {/* Disabled Set Current explanation for completed */}
              {previewItem && previewItem.status === "completed" && (
                <div className="rounded-md border border-techMuted/20 bg-techCardSoft px-3 py-2">
                  <p className="text-xs text-techMuted flex items-center gap-1.5">
                    <AlertCircle size={12} />
                    已完成的议题不能设为当前 / COMPLETED TOPICS CANNOT BE SET CURRENT
                  </p>
                </div>
              )}
            </div>
          ) : (
            /* No center agenda */
            <div className="py-6 text-center">
              <p className="text-xs text-techMuted">
                {isFlowDone
                  ? "所有议题已处理完毕"
                  : "无当前议题 / NO ACTIVE TOPIC"}
              </p>
              {!isFlowDone && !readOnly && meetingActive && sorted.length > 0 && (
                <p className="text-[0.6rem] text-techMuted/70 mt-1">
                  点击左侧议题预览后设为当前
                </p>
              )}
            </div>
          )}
        </div>

        {/* ─── RIGHT: Topic Actions ─────────────────────────────────────────── */}
        <div className="lg:col-span-4 space-y-3">
          <div className="flex items-center justify-between mb-1">
            <span className="inline-flex items-baseline gap-1.5">
              <span className="text-xs font-semibold text-techText">
                议题操作
              </span>
              <span className="text-[0.6rem] font-mono uppercase tracking-wider text-techMuted">
                TOPIC ACTIONS
              </span>
            </span>
          </div>

          {/* No actions when readOnly */}
          {readOnly || !meetingActive ? (
            <div className="py-4 text-center">
              <p className="text-xs text-techMuted">
                {readOnly
                  ? "会议已结束，议程只读"
                  : "会议未激活，操作不可用"}
              </p>
              <p className="text-[0.6rem] font-mono text-techMuted/60 mt-0.5">
                {readOnly ? "READ-ONLY" : "MEETING NOT ACTIVE"}
              </p>
            </div>
          ) : (
            <>
              {/* Set Current — only visible when there's a pending/skipped preview */}
              {previewItem &&
                (previewItem.status === "pending" ||
                  previewItem.status === "skipped") && (
                  <ActionButton
                    variant="primary"
                    size="md"
                    icon={<Play size={14} />}
                    onClick={() => onSetCurrent(previewItem.id)}
                    disabled={!canSetCurrent}
                    loading={busy}
                    className="w-full"
                  >
                    设为当前 / SET CURRENT
                  </ActionButton>
                )}

              {/* Disabled Set Current indicator for completed */}
              {previewItem && previewItem.status === "completed" && (
                <div className="rounded-md border border-techMuted/20 bg-techCardSoft px-3 py-2 text-center">
                  <p className="text-[0.6rem] text-techMuted font-mono">
                    已完成议题 / COMPLETED
                  </p>
                </div>
              )}

              {/* Advance */}
              <ActionButton
                variant="primary"
                size="md"
                icon={<ArrowRight size={14} />}
                onClick={onAdvance}
                disabled={!canAdvance}
                loading={busy}
                className="w-full"
              >
                推进 / ADVANCE
              </ActionButton>

              {/* Complete */}
              <ActionButton
                variant="success"
                size="md"
                icon={<CheckCircle2 size={14} />}
                onClick={() => {
                  if (current) onComplete(current.id);
                }}
                disabled={!canComplete}
                loading={busy}
                className="w-full"
              >
                完成 / COMPLETE
              </ActionButton>

              {/* Skip — amber/warning visual */}
              <ActionButton
                variant="warning"
                size="md"
                icon={<SkipForward size={14} />}
                onClick={() => {
                  if (current) onSkip(current.id);
                }}
                disabled={!canSkip}
                loading={busy}
                className="w-full"
              >
                跳过 / SKIP
              </ActionButton>
            </>
          )}
        </div>
      </div>

      {/* ── Add Agenda Form — show when meeting is active ──────────────────── */}
      {meetingActive && !readOnly && (
        <div className="mt-4 border-t border-techBorder/50 pt-4">
          <div className="flex items-baseline gap-1.5 mb-3">
            <span className="text-xs font-semibold text-techText">
              新增议程
            </span>
            <span className="text-[0.6rem] font-mono uppercase tracking-wider text-techMuted">
              ADD AGENDA
            </span>
          </div>
          <div className="flex gap-2">
            <input
              type="text"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleAdd();
              }}
              placeholder="输入议题标题 / TOPIC TITLE"
              className="flex-1 bg-techSurface border border-techBorder rounded-lg px-3 py-2 text-sm text-techText placeholder:text-techMuted/60 focus:outline-none focus:border-techCyan focus:ring-1 focus:ring-techCyan/30 transition-colors"
            />
            <ActionButton
              variant="primary"
              size="md"
              icon={addBusy ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
              onClick={handleAdd}
              disabled={!newTitle.trim() || addBusy}
              loading={addBusy}
            >
              添加 / ADD
            </ActionButton>
          </div>
        </div>
      )}
    </PanelCard>
  );
}

// ── Backward-compatible alias ───────────────────────────────────────────────
// Keep the old export name so AdminDashboard imports don't break during
// migration.  New code should import AgendaCommandCenter directly.
export { AgendaCommandCenter as AgendaPanel };
