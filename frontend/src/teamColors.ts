// Primary shirt colours for the 20 Premier League clubs, keyed by FPL
// short_name. Kept as one source of truth so PlayerCard, the scouting dot,
// and any future team-coded chip stay consistent. Includes recently
// promoted/relegated sides so the map stays useful across seasons.
export const TEAM_COLORS: Record<string, string> = {
  ARS: "#EF0107", // Arsenal
  AVL: "#670E36", // Aston Villa
  BOU: "#DA020E", // Bournemouth
  BRE: "#E30613", // Brentford
  BHA: "#0057B8", // Brighton
  BUR: "#6C1D45", // Burnley
  CHE: "#034694", // Chelsea
  COV: "#43B5C5", // Coventry
  CRY: "#1B458F", // Crystal Palace
  EVE: "#003399", // Everton
  FUL: "#CCCCCC", // Fulham (black/white — use light grey for contrast on dark theme)
  HUL: "#F18A00", // Hull
  IPS: "#001489", // Ipswich
  LEE: "#FFCD00", // Leeds
  LEI: "#003090", // Leicester
  LIV: "#C8102E", // Liverpool
  LUT: "#F78F1E", // Luton
  MCI: "#6CABDD", // Man City
  MUN: "#DA291C", // Man United
  NEW: "#F0F0F0", // Newcastle (black/white — light for contrast)
  NFO: "#DD0000", // Nottingham Forest
  SHU: "#EE2737", // Sheffield United
  SOU: "#D71920", // Southampton
  SUN: "#EB172B", // Sunderland
  TOT: "#8FA5D9", // Tottenham (navy is close to bg — use light navy for pop)
  WHU: "#7A263A", // West Ham
  WOL: "#FDB913", // Wolves
};

const DEFAULT = "#64748B"; // slate-500

export function teamColor(short: string | null | undefined): string {
  if (!short) return DEFAULT;
  return TEAM_COLORS[short.toUpperCase()] ?? DEFAULT;
}
