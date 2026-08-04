export function SkeletonList({ rows = 4 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-2" aria-busy="true" aria-label="불러오는 중">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-16 animate-pulse rounded-lg bg-sunk" />
      ))}
    </div>
  );
}

export function SkeletonBlock({ className = "h-32" }: { className?: string }) {
  return (
    <div
      aria-busy="true"
      aria-label="불러오는 중"
      className={`animate-pulse rounded-lg bg-sunk ${className}`}
    />
  );
}
