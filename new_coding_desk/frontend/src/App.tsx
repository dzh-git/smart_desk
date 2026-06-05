import { useMemo } from "react";
import { AdminDashboard } from "./components/AdminDashboard";
import { SeatTablet } from "./components/SeatTablet";
import { AlertTriangle, ArrowLeft } from "lucide-react";

// ── URL parameter parsing ────────────────────────────────────────────────────

function useSeatParam(): { seatId: number | null; error: string | null } {
  return useMemo(() => {
    const params = new URLSearchParams(window.location.search);
    const raw = params.get("seat");

    // No seat param → admin mode
    if (raw === null) {
      return { seatId: null, error: null };
    }

    const num = Number(raw);

    // Must be an integer between 1 and 10
    if (!Number.isInteger(num) || num < 1 || num > 10) {
      return {
        seatId: null,
        error: `Invalid seat number: "${raw}". Seat must be an integer between 1 and 10.`,
      };
    }

    return { seatId: num, error: null };
  }, []);
}

export default function App() {
  const { seatId, error: seatError } = useSeatParam();

  // ── Error state (invalid seat parameter) ──────────────────────────────
  if (seatError) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center p-6">
        <div className="w-16 h-16 rounded-full bg-red-50 border-2 border-red-200 flex items-center justify-center mx-auto mb-4">
          <AlertTriangle className="text-red-500" size={28} />
        </div>
        <p className="text-base font-bold text-slate-800 mb-2">
          Invalid Seat Selection
        </p>
        <p className="text-xs text-slate-500 text-center max-w-sm mb-6">
          {seatError}
        </p>
        <a
          href="/"
          className="inline-flex items-center gap-2 text-xs font-medium bg-sky-600 text-white rounded-lg px-4 py-2 hover:bg-sky-700 transition-colors"
        >
          <ArrowLeft size={14} />
          Back to Admin Dashboard
        </a>
      </div>
    );
  }

  // ── Seat mode ─────────────────────────────────────────────────────────
  if (seatId !== null) {
    return (
      <SeatTablet
        seatId={seatId}
        onSwitchToAdmin={() => {
          window.location.href = "/";
        }}
      />
    );
  }

  // ── Admin mode (default) ──────────────────────────────────────────────
  return (
    <AdminDashboard
      onSwitchToSeat={(sid) => {
        window.location.href = `/?seat=${sid}`;
      }}
    />
  );
}
