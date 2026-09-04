import { Link, NavLink, Route, BrowserRouter, Routes } from "react-router-dom";
import { GameweekBadge } from "./components/GameweekBadge";
import { ProjectionsPage } from "./pages/ProjectionsPage";
import { SquadPage } from "./pages/SquadPage";
import { TrackRecordPage } from "./pages/TrackRecordPage";
import { TransfersPage } from "./pages/TransfersPage";

function NavItem({ to, label }: { to: string; label: string }) {
  return (
    <NavLink
      to={to}
      end
      className={({ isActive }) =>
        "px-3 py-1.5 rounded-md text-sm transition " +
        (isActive
          ? "bg-emerald-500/15 text-emerald-300"
          : "text-slate-300 hover:text-white")
      }
    >
      {label}
    </NavLink>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-full flex flex-col">
        <header className="border-b border-white/5 bg-slate-950/70 backdrop-blur sticky top-0 z-10">
          <div className="max-w-6xl mx-auto flex items-center justify-between gap-4 px-6 py-3">
            <Link to="/" className="flex items-center gap-2">
              <span className="text-lg">⚽</span>
              <span className="font-semibold tracking-tight">
                FPL Squad Optimizer
              </span>
            </Link>
            <div className="flex items-center gap-4">
              <GameweekBadge />
              <nav className="flex gap-1">
                <NavItem to="/" label="Squad" />
                <NavItem to="/transfers" label="Transfers" />
                <NavItem to="/projections" label="Projections" />
                <NavItem to="/record" label="Record" />
              </nav>
            </div>
          </div>
        </header>
        <main className="flex-1">
          <div className="max-w-6xl mx-auto px-6 py-8">
            <Routes>
              <Route path="/" element={<SquadPage />} />
              <Route path="/transfers" element={<TransfersPage />} />
              <Route path="/projections" element={<ProjectionsPage />} />
              <Route path="/record" element={<TrackRecordPage />} />
            </Routes>
          </div>
        </main>
      </div>
    </BrowserRouter>
  );
}
