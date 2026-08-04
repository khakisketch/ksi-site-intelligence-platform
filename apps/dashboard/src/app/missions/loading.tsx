export default function MissionsLoading() {
  return (
    <div className="flex flex-col gap-4 p-4 sm:p-5" aria-busy="true" aria-label="불러오는 중">
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-32 animate-pulse rounded-lg bg-sunk" />
        ))}
      </div>
    </div>
  );
}
