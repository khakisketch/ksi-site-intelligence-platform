export function ErrorState({ message, detail }: { message: string; detail?: string }) {
  return (
    <div
      role="alert"
      className="flex flex-col gap-1 rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-900 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-100"
    >
      <p className="font-medium break-keep">{message}</p>
      {detail && <p className="text-red-800/80 break-keep dark:text-red-200/70">{detail}</p>}
    </div>
  );
}
