"use client";

import { useState } from "react";
import { format } from "date-fns";

import { postCheckIn, type CheckInResult, type CheckInTask } from "@/lib/api";

type Row = { spent: string; done: boolean; left: string };

const inputCls =
  "w-16 rounded border border-line bg-raised px-1.5 py-1 text-right font-mono text-xs text-fg focus:border-accent/60 focus:outline-none";

const fmt = (h: number) => `${Number(h.toFixed(2))}h`;

/**
 * The weekly check-in: what was planned since last time, and what really
 * happened. Hours spent default to what was planned, so a week that went to
 * plan is one click. Finishing a task teaches its course how long work really
 * takes; "hours left" corrects a single task without touching the rest.
 */
export default function CheckInPanel({
  since,
  tasks,
  onDone,
}: {
  since: string | null;
  tasks: CheckInTask[];
  onDone: (result: CheckInResult) => void;
}) {
  const [rows, setRows] = useState<Record<string, Row>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!tasks.length) return null;

  const row = (t: CheckInTask): Row =>
    rows[t.assignment_id] ?? { spent: String(Number(t.planned_hours.toFixed(2))), done: false, left: "" };
  const set = (t: CheckInTask, patch: Partial<Row>) =>
    setRows({ ...rows, [t.assignment_id]: { ...row(t), ...patch } });

  const valid = tasks.every((t) => {
    const r = row(t);
    return r.spent !== "" && Number(r.spent) >= 0 && (r.left === "" || Number(r.left) >= 0);
  });

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const result = await postCheckIn(
        tasks.map((t) => {
          const r = row(t);
          return {
            assignment_id: t.assignment_id,
            hours_spent: Number(r.spent),
            done: r.done,
            ...(!r.done && r.left !== "" ? { hours_left: Number(r.left) } : {}),
          };
        }),
      );
      setRows({});
      onDone(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="rounded-xl border border-accent/40 bg-surface p-5">
      <h2 className="text-sm font-semibold text-accent">Check in</h2>
      <p className="mt-0.5 text-[11px] text-muted">
        {since && <>Since {format(new Date(`${since}T00:00`), "EEE MMM d")}. </>}
        How much did you actually do? Future estimates adjust to match.
      </p>

      <ul className="mt-3 space-y-3">
        {tasks.map((t) => {
          const r = row(t);
          const remaining = Math.max(
            0,
            t.estimated_hours - t.completed_hours - (Number(r.spent) || 0),
          );
          return (
            <li key={t.assignment_id} className="text-xs">
              <div className="flex items-baseline justify-between gap-2">
                <span className="min-w-0 truncate text-fg" title={t.title}>
                  {t.title}
                  <span className="ml-1 text-muted">{t.course_code}</span>
                </span>
                <span className="shrink-0 font-mono text-[10.5px] text-muted">
                  planned {fmt(t.planned_hours)}
                </span>
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[11px] text-muted">
                <label className="flex items-center gap-1.5">
                  Spent
                  <input
                    type="number"
                    min={0}
                    step={0.25}
                    value={r.spent}
                    onChange={(e) => set(t, { spent: e.target.value })}
                    className={inputCls}
                    aria-label={`Hours spent on ${t.title}`}
                  />
                  h
                </label>
                <label className="flex items-center gap-1.5 text-fg/90">
                  <input
                    type="checkbox"
                    checked={r.done}
                    onChange={(e) => set(t, { done: e.target.checked })}
                  />
                  Finished
                </label>
                {!r.done && (
                  <label className="flex items-center gap-1.5">
                    Left
                    <input
                      type="number"
                      min={0}
                      step={0.25}
                      value={r.left}
                      placeholder={String(Number(remaining.toFixed(2)))}
                      onChange={(e) => set(t, { left: e.target.value })}
                      className={inputCls}
                      aria-label={`Hours left on ${t.title}`}
                    />
                    h
                  </label>
                )}
              </div>
            </li>
          );
        })}
      </ul>

      {error && <p className="mt-2 text-xs text-red-300">{error}</p>}
      <button
        onClick={save}
        disabled={saving || !valid}
        className="mt-4 rounded bg-accent px-3 py-1.5 text-xs font-semibold text-ground disabled:opacity-40"
      >
        {saving ? "Saving…" : "Save check-in"}
      </button>
      <p className="mt-1.5 text-[10.5px] text-faint">
        Leave &ldquo;Left&rdquo; blank to keep the current estimate.
      </p>
    </section>
  );
}

/** One line on what the check-in learned, for the page to show. */
export function describeCheckIn(r: CheckInResult): string {
  if (!r.adjustments.length) return "Check-in saved. Your plan is updated.";
  return r.adjustments
    .map((a) => {
      const pct = Math.round((a.after - 1) * 100);
      const trend =
        pct > 0 ? `runs about ${pct}% over estimates` : pct < 0 ? `runs about ${-pct}% under estimates` : "is back on its estimates";
      const re = a.rescaled ? ` ${a.rescaled} upcoming task${a.rescaled === 1 ? "" : "s"} re-estimated.` : "";
      return `${a.course_code} ${trend}.${re}`;
    })
    .join(" ");
}
