export type NavIconName =
  | "home"
  | "sites"
  | "work"
  | "review"
  | "more"
  | "flight"
  | "connection"
  | "support";

const PATHS: Record<NavIconName, React.ReactNode> = {
  home: <><path d="M3 10.5 12 3l9 7.5" /><path d="M5.5 9.5V21h13V9.5" /></>,
  sites: <><path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3Z" /><path d="M9 3v15M15 6v15" /></>,
  work: <><rect x="4" y="5" width="16" height="16" rx="2" /><path d="M9 5V3h6v2M8 11h8M8 15h6" /></>,
  review: <><circle cx="12" cy="12" r="9" /><path d="m8 12 2.5 2.5L16 9" /></>,
  more: <><circle cx="5" cy="12" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="19" cy="12" r="1" /></>,
  flight: <><path d="M2 16 22 8l-8 14-2-8Z" /><path d="m12 14-4-3" /></>,
  connection: <><path d="M5 9a10 10 0 0 1 14 0M8 12a6 6 0 0 1 8 0M11 15a2 2 0 0 1 2 0" /><circle cx="12" cy="19" r="1" /></>,
  support: <><path d="M12 3a9 9 0 1 0 9 9" /><path d="M12 7v5l3 2M16 3h5v5" /></>,
};

export function NavIcon({ name, className = "size-5" }: { name: NavIconName; className?: string }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      {PATHS[name]}
    </svg>
  );
}
