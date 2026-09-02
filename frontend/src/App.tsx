import { Link, NavLink, Route, BrowserRouter, Routes } from "react-router-dom";
import { ProjectionsPage } from "./pages/ProjectionsPage";
import { SquadPage } from "./pages/SquadPage";
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
          <div className="max-w-6xl mx-auto flex items-center justify-between px-6 py-3">
            <Link to="/" className="flex items-center gap-2">
              <span className="text-lg">⚽</span>
              <span className="font-semibold tracking-tight">
                FPL Squad Optimizer
              </span>
            </Link>
            <nav className="flex gap-1">
              <NavItem to="/" label="Squad" />
              <NavItem to="/transfers" label="Transfers" />
              <NavItem to="/projections" label="Projections" />
            </nav>
          </div>
        </header>
        <main className="flex-1">
          <div className="max-w-6xl mx-auto px-6 py-8">
            <Routes>
              <Route path="/" element={<SquadPage />} />
              <Route path="/transfers" element={<TransfersPage />} />
              <Route path="/projections" element={<ProjectionsPage />} />
            </Routes>
          </div>
        </main>
      </div>
    </BrowserRouter>
  );
}
