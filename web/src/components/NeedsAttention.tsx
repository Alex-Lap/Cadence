"use client";

import { useState } from "react";

import { patchAssignment, reschedule, type Assignment } from "@/lib/api";

/**
 * The follow-up form after an upload.
 *
 * Both real test syllabi landed here, so this is the common path rather than an
 * edge case: extraction finds the graded work but not always its dates, and it
 * sometimes labels a real exam as a grading bucket.
 *
 * Edits are collected locally and saved together -- PATCH deliberately does not
 * reschedule, so five corrections cost one rebuild instead of five.
 */
export default function NeedsAttention({
  assignments,
  onChanged,
}: {
  assignments: Assignment[];
  onChanged: () => void;
}) {
  const [dates, setDates] = useState<Record<string, string>>({});
  const [promote, setPromote] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const needsDate = assignments.filter((a) => a.needs_date);
  const categories = assignments.filter((a) => a.is_category);
  if (!needsDate.length && !categories.length) return null;

  const pending =
    Object.values(dates).filter(Boolean).length + Object.values(promote).filter(Boolean).length;

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const ids = new Set([...Object.keys(dates), ...Object.keys(promote)]);
      for (const id of ids) {
        const patch: Parameters<typeof patchAssignment>[1] = {};
        if (dates[id]) patch.due_at = `${dates[id]}T00:00:00`;
        if (promote[id]) patch.is_category = false;
        if (Object.keys(patch).length) await patchAssignment(id, patch);
      }
      await reschedule();
      setDates({});
      setPromote({});
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="rounded-xl border border-warn/40 bg-surface p-5">
      <h2 className="text-sm font-semibold text-warn">Needs your input</h2>

      {needsDate.length > 0 && (
        <div className="mt-3">
          <h3 className="text-xs font-medium text-warn">No due date found</h3>
          <ul className="mt-2 space-y-2">
            {needsDate.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center gap-2 text-xs">
                <span className="min-w-40 flex-1 text-fg">
                  {a.title}
                  <span className="ml-1 text-muted">
                    {a.course_code}
                    {a.weight != null && ` · ${Math.round(a.weight * 100)}%`}
                  </span>
                </span>
                <input
                  id={`due-${a.id}`}
                  type="date"
                  value={dates[a.id] ?? ""}
                  onChange={(e) => setDates({ ...dates, [a.id]: e.target.value })}
                  className="rounded border border-line bg-raised px-2 py-1 text-fg"
                />
              </li>
            ))}
          </ul>
        </div>
      )}

      {categories.length > 0 && (
        <div className="mt-4">
          <h3 className="text-xs font-medium text-warn">Grading categories</h3>
          <p className="mt-1 text-[11px] text-muted">
            Buckets, not deliverables, so they aren&apos;t scheduled. If one is actually a
            single piece of work, tick it and give it a date.
          </p>
          <ul className="mt-2 space-y-2">
            {categories.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center gap-2 text-xs">
                <label className="flex min-w-40 flex-1 items-center gap-2 text-fg">
                  <input
                    id={`promote-${a.id}`}
                    type="checkbox"
                    checked={promote[a.id] ?? false}
                    onChange={(e) => setPromote({ ...promote, [a.id]: e.target.checked })}
                  />
                  {a.title}
                  <span className="text-muted">
                    {a.course_code}
                    {a.weight != null && ` · ${Math.round(a.weight * 100)}%`}
                  </span>
                </label>
                <input
                  id={`cat-due-${a.id}`}
                  type="date"
                  value={dates[a.id] ?? ""}
                  onChange={(e) => setDates({ ...dates, [a.id]: e.target.value })}
                  disabled={!promote[a.id]}
                  className="rounded border border-line bg-raised px-2 py-1 text-fg disabled:opacity-40"
                />
              </li>
            ))}
          </ul>
        </div>
      )}

      {error && <p className="mt-3 text-xs text-red-300">{error}</p>}

      <button
        onClick={save}
        disabled={saving || pending === 0}
        className="mt-4 rounded bg-warn px-3 py-1.5 text-xs font-semibold text-ground disabled:opacity-40"
      >
        {saving ? "Saving…" : `Save ${pending || ""} and reschedule`}
      </button>
    </section>
  );
}
