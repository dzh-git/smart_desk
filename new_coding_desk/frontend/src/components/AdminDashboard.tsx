import { useState, useCallback } from "react";
import { Loader2, AlertCircle, Cpu, RefreshCw, Vote, XCircle } from "lucide-react";
import { useAdminData } from "../hooks/useAdminData";
import { AdminHeader } from "./AdminHeader";
import { ConferenceTable } from "./ConferenceTable";
import { AgendaPanel } from "./AgendaPanel";
import { VotePanel } from "./VotePanel";
import { ServicePanel } from "./ServicePanel";
import { TranscriptPanel } from "./TranscriptPanel";
import { SectionCard } from "./shared";
import { formatDuration, isDemoControlsEnabled } from "./shared";
import { createVote, closeVote, resolveServiceCall } from "../api/resources";

interface AdminDashboardProps {
  onSwitchToSeat: (seatId: number) => void;
}

export function AdminDashboard({ onSwitchToSeat }: AdminDashboardProps) {
  const {
    loading,
    error,
    meeting,
    seats,
    speakerSeatId,
    attendees,
    agenda,
    activeVote,
    hasActiveVote,
    voteStatsError,
    serviceCalls,
    translations,
    connection,
    noMeeting,
    refresh,
  } = useAdminData();

  const [activeSeatId, setActiveSeatId] = useState<number | undefined>();
  const [previewSeat, setPreviewSeat] = useState(1);

  // ── Admin action state ─────────────────────────────────────────────────
  const [createVoteTitle, setCreateVoteTitle] = useState("");
  const [createVoteOptions, setCreateVoteOptions] = useState(["", ""]);
  const [createVoteAnonymous, setCreateVoteAnonymous] = useState(false);
  const [creatingVote, setCreatingVote] = useState(false);
  const [closingVote, setClosingVote] = useState(false);
  const [adminActionError, setAdminActionError] = useState<string | null>(null);
  const [resolvingId, setResolvingId] = useState<number | null>(null);

  // ── Admin action handlers ──────────────────────────────────────────────

  const handleCreateVote = useCallback(async () => {
    if (!meeting?.id) return;
    const trimmedTitle = createVoteTitle.trim();
    if (!trimmedTitle) {
      setAdminActionError("Vote title is required");
      return;
    }
    const validOptions = createVoteOptions
      .map((o) => o.trim())
      .filter((o) => o.length > 0);
    if (validOptions.length < 2) {
      setAdminActionError("At least 2 non-empty options are required");
      return;
    }
    setCreatingVote(true);
    setAdminActionError(null);
    try {
      await createVote(meeting.id, trimmedTitle, validOptions, createVoteAnonymous);
      setCreateVoteTitle("");
      setCreateVoteOptions(["", ""]);
      setCreateVoteAnonymous(false);
      refresh();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to create vote";
      setAdminActionError(msg);
    } finally {
      setCreatingVote(false);
    }
  }, [meeting?.id, createVoteTitle, createVoteOptions, createVoteAnonymous, refresh]);

  const handleCloseVote = useCallback(async (voteId: number) => {
    setClosingVote(true);
    setAdminActionError(null);
    try {
      await closeVote(voteId);
      refresh();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to close vote";
      setAdminActionError(msg);
    } finally {
      setClosingVote(false);
    }
  }, [refresh]);

  const handleResolveCall = useCallback(async (callId: number) => {
    setResolvingId(callId);
    setAdminActionError(null);
    try {
      await resolveServiceCall(callId);
      refresh();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to resolve service call";
      setAdminActionError(msg);
    } finally {
      setResolvingId(null);
    }
  }, [refresh]);

  function handleSeatClick(seatId: number) {
    setActiveSeatId((prev) => (prev === seatId ? undefined : seatId));
  }

  // Build seat → name map for service calls and transcript
  const seatNameMap: Record<number, string> = {};
  for (const a of attendees) {
    if (a.seat_id != null) {
      seatNameMap[a.seat_id] = a.name;
    }
  }

  // Metric card data
  const checkedIn = attendees.filter((a) => a.checked_in).length;
  const speakerAttendee =
    speakerSeatId != null ? seatNameMap[speakerSeatId] ?? null : null;
  const pendingRequests = serviceCalls.filter(
    (c) => c.status === "pending",
  ).length;
  const elapsedMs =
    meeting?.started_at != null
      ? Date.now() - new Date(meeting.started_at).getTime()
      : 0;

  // ── Loading State ──────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col">
        <AdminHeader
          title=""
          meetingStatus="pending"
          connection={connection}
          onModeSwitch={isDemoControlsEnabled() ? () => onSwitchToSeat(previewSeat) : undefined}
          previewSeat={isDemoControlsEnabled() ? previewSeat : undefined}
        />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center space-y-4">
            <Loader2 size={32} className="animate-spin text-sky-500 mx-auto" />
            <p className="text-sm font-medium text-slate-600">
              Loading meeting data...
            </p>
          </div>
        </div>
      </div>
    );
  }

  // ── Error State ────────────────────────────────────────────────────────
  if (error) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col">
        <AdminHeader
          title=""
          meetingStatus="pending"
          connection={connection}
          onModeSwitch={isDemoControlsEnabled() ? () => onSwitchToSeat(previewSeat) : undefined}
          previewSeat={isDemoControlsEnabled() ? previewSeat : undefined}
        />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center space-y-4 max-w-md">
            <div className="w-14 h-14 rounded-full bg-red-50 border-2 border-red-200 flex items-center justify-center mx-auto">
              <AlertCircle className="text-red-500" size={24} />
            </div>
            <p className="text-sm font-semibold text-slate-800">
              Failed to load data
            </p>
            <p className="text-xs text-slate-500">{error}</p>
            <button
              onClick={refresh}
              className="inline-flex items-center gap-2 text-xs font-medium bg-sky-600 text-white rounded-lg px-4 py-2 hover:bg-sky-700 transition-colors"
            >
              <RefreshCw size={14} />
              Retry
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ── No Meeting State ───────────────────────────────────────────────────
  if (noMeeting) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col">
        <AdminHeader
          title=""
          meetingStatus="pending"
          connection={connection}
          onModeSwitch={isDemoControlsEnabled() ? () => onSwitchToSeat(previewSeat) : undefined}
          previewSeat={isDemoControlsEnabled() ? previewSeat : undefined}
        />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center space-y-4 max-w-md">
            <div className="w-16 h-16 rounded-full bg-sky-50 border-2 border-sky-200 flex items-center justify-center mx-auto">
              <Cpu className="text-sky-500" size={28} />
            </div>
            <p className="text-base font-bold text-slate-800">
              Waiting for Meeting
            </p>
            <p className="text-xs text-slate-500">
              The admin dashboard will load automatically once a meeting is
              started.
            </p>
            <button
              onClick={refresh}
              className="inline-flex items-center gap-2 text-xs font-medium bg-sky-100 text-sky-700 border border-sky-200 rounded-lg px-4 py-2 hover:bg-sky-200 transition-colors"
            >
              <RefreshCw size={14} />
              Refresh
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ── Active Meeting ─────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-slate-50 flex flex-col relative">
      <AdminHeader
        title={meeting?.title ?? ""}
        meetingStatus={meeting?.status ?? "pending"}
        connection={connection}
        onModeSwitch={isDemoControlsEnabled() ? () => onSwitchToSeat(previewSeat) : undefined}
        previewSeat={isDemoControlsEnabled() ? previewSeat : undefined}
      />

      {/* Seat preview selector — only visible in demo mode */}
      {isDemoControlsEnabled() && (
        <div className="bg-slate-900 border-t border-slate-800 px-6 py-2 flex items-center gap-3">
          <span className="text-xs text-slate-500 font-medium">
            Preview seat:
          </span>
          <div className="flex gap-1.5">
            {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
              <button
                key={n}
                onClick={() => setPreviewSeat(n)}
                className={`w-7 h-7 rounded-md text-xs font-semibold transition-colors ${
                  previewSeat === n
                    ? "bg-sky-500 text-white"
                    : "bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-slate-300"
                }`}
              >
                {n}
              </button>
            ))}
          </div>
          <button
            onClick={() => onSwitchToSeat(previewSeat)}
            className="ml-auto text-xs font-medium text-sky-400 border border-sky-800 hover:bg-sky-900/50 transition-colors rounded-lg px-3 py-1"
          >
            Open Seat Tablet View
          </button>
        </div>
      )}

      <main className="flex-1 p-6 overflow-auto">
        {/* Summary row */}
        <div className="mb-6">
          <div className="grid grid-cols-4 gap-3">
            <MetricCard
              label="Elapsed"
              value={elapsedMs > 0 ? formatDuration(elapsedMs) : "—"}
              sub="Meeting time"
              accent="text-sky-700"
            />
            <MetricCard
              label="Attendees"
              value={`${checkedIn}/10`}
              sub="Checked in"
              accent={
                checkedIn >= 9 ? "text-emerald-700" : "text-amber-600"
              }
            />
            <MetricCard
              label="Speaker"
              value={speakerAttendee?.split(" ")[0] ?? "—"}
              sub={speakerAttendee ?? "No active speaker"}
              accent="text-emerald-700"
            />
            <MetricCard
              label="Requests"
              value={pendingRequests}
              sub="Pending service"
              accent={
                pendingRequests > 0 ? "text-rose-600" : "text-slate-600"
              }
            />
          </div>
        </div>

        {/* Main grid */}
        <div className="grid grid-cols-12 gap-6">
          {/* Conference table — wide */}
          <div className="col-span-12 xl:col-span-8">
            <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6">
              <h3 className="text-xs font-semibold uppercase tracking-widest text-slate-500 mb-5">
                Conference Room — Seat Overview
              </h3>
              <ConferenceTable
                seats={seats}
                currentSpeaker={speakerSeatId}
                activeSeat={activeSeatId}
                onSeatClick={handleSeatClick}
              />
            </div>
          </div>

          {/* Right column */}
          <div className="col-span-12 xl:col-span-4 flex flex-col gap-6">
            <AgendaPanel agenda={agenda} />

            {/* Admin action error */}
            {adminActionError && (
              <div className="bg-rose-50 border border-rose-200 rounded-xl px-4 py-3 flex items-center gap-2">
                <AlertCircle size={14} className="text-rose-500 flex-shrink-0" />
                <p className="text-xs text-rose-700">{adminActionError}</p>
                <button
                  onClick={() => setAdminActionError(null)}
                  className="ml-auto text-rose-400 hover:text-rose-600"
                >
                  <XCircle size={14} />
                </button>
              </div>
            )}

            {/* Create Vote form — only when no active vote (use hasActiveVote so it stays hidden when stats fail to load) */}
            {!hasActiveVote && meeting && (
              <SectionCard title="Create Vote">
                <div className="space-y-3">
                  <input
                    type="text"
                    value={createVoteTitle}
                    onChange={(e) => setCreateVoteTitle(e.target.value)}
                    placeholder="Vote title..."
                    className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-400 focus:border-transparent"
                  />
                  {createVoteOptions.map((opt, i) => (
                    <input
                      key={i}
                      type="text"
                      value={opt}
                      onChange={(e) => {
                        const next = [...createVoteOptions];
                        next[i] = e.target.value;
                        setCreateVoteOptions(next);
                      }}
                      placeholder={`Option ${i + 1}`}
                      className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-400 focus:border-transparent"
                    />
                  ))}
                  <button
                    onClick={() => setCreateVoteOptions([...createVoteOptions, ""])}
                    className="text-xs font-medium text-sky-600 hover:text-sky-700"
                  >
                    + Add option
                  </button>
                  <label className="flex items-center gap-2 text-xs text-slate-600">
                    <input
                      type="checkbox"
                      checked={createVoteAnonymous}
                      onChange={(e) => setCreateVoteAnonymous(e.target.checked)}
                      className="rounded border-slate-300"
                    />
                    Anonymous vote
                  </label>
                  <button
                    onClick={handleCreateVote}
                    disabled={creatingVote}
                    className="w-full inline-flex items-center justify-center gap-2 text-xs font-medium bg-sky-600 text-white rounded-lg px-4 py-2 hover:bg-sky-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {creatingVote ? (
                      <Loader2 size={12} className="animate-spin" />
                    ) : (
                      <Vote size={14} />
                    )}
                    {creatingVote ? "Creating..." : "Create Vote"}
                  </button>
                </div>
              </SectionCard>
            )}

            <VotePanel vote={activeVote} hasActiveVote={hasActiveVote} voteStatsError={voteStatsError} onRetryStats={refresh} onCloseVote={handleCloseVote} closingVote={closingVote} />
            <ServicePanel calls={serviceCalls} seatNameMap={seatNameMap} onResolve={handleResolveCall} resolvingId={resolvingId} />
          </div>
        </div>

        {/* Transcript row */}
        <div className="mt-6">
          <TranscriptPanel
            entries={translations}
            seatNameMap={seatNameMap}
          />
        </div>
      </main>

      {/* Disconnected overlay */}
      {connection === "disconnected" && (
        <div className="fixed inset-0 bg-white/80 backdrop-blur-sm flex flex-col items-center justify-center z-50">
          <div className="w-14 h-14 rounded-full bg-red-50 border-2 border-red-200 flex items-center justify-center mb-4">
            <div className="text-red-500">
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="24"
                height="24"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <line x1="1" y1="1" x2="23" y2="23" />
                <path d="M16.72 11.06A10.94 10.94 0 0 1 19 12.55" />
                <path d="M5 12.55a10.94 10.94 0 0 1 5.17-2.39" />
                <path d="M10.71 5.05A16 16 0 0 1 22.56 9" />
                <path d="M1.42 9a15.91 15.91 0 0 1 4.7-2.88" />
                <path d="M8.53 16.11a6 6 0 0 1 6.95 0" />
                <line x1="12" y1="20" x2="12.01" y2="20" />
              </svg>
            </div>
          </div>
          <p className="text-sm font-semibold text-slate-800 mb-1">
            Connection Lost
          </p>
          <p className="text-xs text-slate-500 mb-4">
            Attempting to reconnect...
          </p>
          <button
            onClick={refresh}
            className="inline-flex items-center gap-2 text-xs font-medium text-sky-600 border border-sky-200 rounded-full px-4 py-1.5 hover:bg-sky-50 transition-colors"
          >
            <RefreshCw size={12} />
            Retry Now
          </button>
        </div>
      )}
    </div>
  );
}

// ── Metric Card ─────────────────────────────────────────────────────────────

interface MetricCardProps {
  label: string;
  value: string | number;
  sub?: string;
  accent?: string;
}

function MetricCard({
  label,
  value,
  sub,
  accent = "text-slate-800",
}: MetricCardProps) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm px-4 py-3 text-center">
      <p className={`text-2xl font-bold leading-none ${accent}`}>{value}</p>
      <p className="text-xs font-medium text-slate-500 mt-1">{label}</p>
      {sub && <p className="text-[10px] text-slate-400 mt-0.5">{sub}</p>}
    </div>
  );
}
