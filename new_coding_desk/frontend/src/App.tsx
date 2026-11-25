import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";
import { AlertTriangle, ArrowLeft } from "lucide-react";
import { AdminDashboard } from "./components/AdminDashboard";
import { SeatTablet } from "./components/SeatTablet";
import { FaceTemplateManager } from "./components/FaceTemplateManager";
import { HostTabletConsole } from "./components/HostTabletConsole";
import { DisplayView } from "./components/DisplayView";
import { ScreenView } from "./components/ScreenView";
import { isDemoControlsEnabled } from "./components/shared";
import { SpatialProvider } from "./spatial/SpatialProvider";

export default function App() {
  return (
    <BrowserRouter>
      <SpatialProvider>
        <Routes>
          <Route path="/" element={<LegacyRootRedirect />} />
          <Route path="/admin" element={<AdminRoute />} />
          <Route path="/host" element={<HostTabletConsole />} />
          <Route path="/seat/:seatId" element={<SeatRoute />} />
          <Route path="/seat/1/face-templates" element={<FaceTemplateManager />} />
          <Route path="/display" element={<DisplayView />} />
          <Route path="/screen" element={<ScreenView />} />
          <Route path="*" element={<Navigate to="/admin" replace />} />
        </Routes>
      </SpatialProvider>
    </BrowserRouter>
  );
}

function LegacyRootRedirect() {
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  const rawSeat = params.get("seat");

  if (rawSeat != null) {
    return <Navigate to={`/seat/${encodeURIComponent(rawSeat)}`} replace />;
  }

  return <Navigate to="/admin" replace />;
}

function AdminRoute() {
  const navigate = useNavigate();
  return (
    <AdminDashboard
      onSwitchToSeat={(sid) => {
        navigate(`/seat/${sid}`);
      }}
    />
  );
}

function SeatRoute() {
  const navigate = useNavigate();
  const { seatId: rawSeatId } = useParams();
  const parsed = parseSeatId(rawSeatId);

  if (parsed.error || parsed.seatId == null) {
    return <InvalidSeatSelection message={parsed.error} />;
  }

  if (parsed.seatId === 1) {
    return <Navigate to="/host" replace />;
  }

  return (
    <SeatTablet
      key={parsed.seatId}
      seatId={parsed.seatId}
      onSwitchToAdmin={
        isDemoControlsEnabled()
          ? () => {
              navigate("/admin");
            }
          : undefined
      }
    />
  );
}

function parseSeatId(
  raw: string | undefined,
): { seatId: number; error: null } | { seatId: null; error: string } {
  const num = Number(raw);
  if (!raw || !Number.isInteger(num) || num < 1 || num > 9) {
    return {
      seatId: null,
      error: `Invalid seat number: "${raw ?? ""}". Seat must be an integer between 1 and 9.`,
    };
  }
  return { seatId: num, error: null };
}

function InvalidSeatSelection({ message }: { message: string }) {
  return (
    <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center p-6">
      <div className="w-16 h-16 rounded-full bg-red-50 border-2 border-red-200 flex items-center justify-center mx-auto mb-4">
        <AlertTriangle className="text-red-500" size={28} />
      </div>
      <p className="text-base font-bold text-slate-800 mb-2">
        Invalid Seat Selection
      </p>
      <p className="text-xs text-slate-500 text-center max-w-sm mb-6">
        {message}
      </p>
      <a
        href="/admin"
        className="inline-flex items-center gap-2 text-xs font-medium bg-sky-600 text-white rounded-lg px-4 py-2 hover:bg-sky-700 transition-colors"
      >
        <ArrowLeft size={14} />
        Back to Admin Dashboard
      </a>
    </div>
  );
}
