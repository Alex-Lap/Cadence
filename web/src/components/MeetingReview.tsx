"use client";

import { useState } from "react";

import TimeSelect from "@/components/TimeSelect";
import {
  deleteCommitment,
  patchCommitment,
  type Commitment,
} from "@/lib/api";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

type Group = {
  key: string;
  title: string;
  course: string | null;
  start: string; // "HH:MM"
  end: string;
  note: string | null;
  warning: string | null;
  rows: Commitment[];
};

/**
 * Class times read from a syllabus, waiting to be checked.
 *
 * One weekly meeting is stored as one row per weekday; here they're grouped
 * back into "CIS 6307 · Tue, Thu 6:00-8:40pm" so the user confirms a meeting,
 * not a row. Nothing is scheduled around these until confirmed, so a misread
 * time can't quietly eat (or free up) an evening.
 */
export default function MeetingReview({
  meetings,
  onChanged,
}: {
  meetings: Commitment[];
  onChanged: () => void;
}) {
  const groups = new Map<string, Group>();
  for (const m of meetings) {
    const key = [m.course_id, m.title, m.start_time, m.end_time, m.note].join("|");
    const g = groups.get(key) ?? {
      key,
      title: m.title,
      course: m.course_code,
      start: m.start_time.slice(0, 5),
      end: m.end_time.slice(0, 5),
      note: m.note,
      warning: m.warning,
      rows: [],
    };
    g.rows.push(m);
    groups.set(key, g);
  }

  return (
    <div className="mt-3">
      <h3 className="text-xs font-medium text-warn">Class times from your syllabus</h3>
      <p className="mt-1 text-[11px] text-muted">
        Check these against the syllabus. Study is planned around them once you
        confirm.
      </p>
      <ul className="mt-2 space-y-2.5">
        {[...groups.values()].map((g) => (
          <MeetingRow key={g.key} group={g} onChanged={onChanged} />
        ))}
      </ul>
    </div>
  );
}

function MeetingRow({ group, onChanged }: { group: Group; onChanged: () => void }) {
  const [start, setStart] = useState(group.start);
  const [end, setEnd] = useState(group.end);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const edited = start !== group.start || end !== group.end;
  const days = group.rows
    .map((r) => r.weekday)
    .filter((d): d is number => d !== null)
    .sort()
    .map((d) => DAYS[d])
    .join(", ");

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const confirm = () =>
    act(async () => {
      for (const r of group.rows) {
        await patchCommitment(r.id, {
          ...(edited ? { start_time: start, end_time: end } : {}),
          confirmed: true,
        });
      }
    });

  const discard = () =>
    act(async () => {
      for (const r of group.rows) await deleteCommitment(r.id);
    });

  return (
    <li
      className={`rounded-lg border p-2.5 text-xs ${group.warning && !edited ? "border-red-400/40 bg-red-500/5" : "border-line bg-raised/40"}`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-medium text-fg">{group.title}</span>
        <span className="text-[11px] text-muted">{days}</span>
      </div>
      {group.note && (
        <p className="mt-0.5 truncate text-[11px] italic text-faint" title={group.note}>
          “{group.note}”
        </p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1.5 text-[11px] text-muted">
        <TimeSelect label={`${group.title} starts`} value={start} onChange={setStart} />
        to
        <TimeSelect label={`${group.title} ends`} value={end} onChange={setEnd} />
      </div>
      {group.warning && !edited && (
        <p className="mt-1.5 text-[11px] text-red-300">{group.warning}</p>
      )}
      {end <= start && <p className="mt-1.5 text-[11px] text-red-300">Ends before it starts.</p>}
      <div className="mt-2 flex gap-2">
        <button
          onClick={confirm}
          disabled={busy || end <= start}
          className="rounded bg-warn px-2.5 py-1 text-[11px] font-semibold text-ground disabled:opacity-40"
        >
          {edited ? "Save and confirm" : "Confirm"}
        </button>
        <button
          onClick={discard}
          disabled={busy}
          className="rounded px-2.5 py-1 text-[11px] text-muted hover:text-red-300 disabled:opacity-40"
        >
          Not a class time
        </button>
      </div>
      {error && <p className="mt-1.5 text-[11px] text-red-300">{error}</p>}
    </li>
  );
}
