import Link from "next/link";

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: { label: string; href: string };
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-black/15 px-6 py-12 text-center dark:border-white/15">
      <p className="text-base font-medium break-keep">{title}</p>
      {description && (
        <p className="text-foreground/70 max-w-sm text-sm break-keep">{description}</p>
      )}
      {action && (
        <Link
          href={action.href}
          className="bg-foreground text-background mt-2 inline-flex min-h-11 items-center rounded-md px-4 text-sm font-medium"
        >
          {action.label}
        </Link>
      )}
    </div>
  );
}
