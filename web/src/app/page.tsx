"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import CheckInPanel, { describeCheckIn } from "@/components/CheckInPanel";
import NeedsAttention from "@/components/NeedsAttention";
import TaskList from "@/components/TaskList";
import { taskColors } from "@/lib/colors";
import ScheduleCalendar from "@/components/ScheduleCalendar";
import SettingsPanel from "@/components/SettingsPanel";
import UploadPanel from "@/components/UploadPanel";
import {
  deleteCourse,
  getAssignments,
  getCheckIn,
  getCommitments,
  getCourses,
  getSchedule,
  getSettings,
  calendarExportUrl,
  patchBlock,
  reschedule,
  toDateStr,
  toTimeStr,
  type Assignment,
  type Block,
  type CheckInTask,
  type Commitment,
  type Course,
  type SettingsOut,
} from "@/lib/api";

type Change = { kept: number; moved: number; ids: Set<string> };

const sig = (b: Block) => `${b.assignment_id}|${b.day}|${b.start_time}|${b.hours}`;

/**
 * Compare two plans by what they schedule, not by row id (ids are new on every
 * rebuild). Returns the ids of blocks that are new or moved, and how many old
 * blocks didn't survive. Blocks the user pinned are their own doing, so they
 * don't count as the plan moving.
 */
function diffPlans(before: Block[], after: Block[]): Change {
  const pool = new Map<string, number>();
  for (const b of before) if (!b.pinned) pool.set(sig(b), (pool.get(sig(b)) ?? 0) + 1);
  const ids = new Set<string>();
  let kept = 0;
  for (const b of after) {
    if (b.pinned) continue;
    const n = pool.get(sig(b)) ?? 0;
    if (n > 0) {
      pool.set(sig(b), n - 1);
      kept++;
    } else ids.add(b.id);
  }
  const newlyPinned =
    after.filter((b) => b.pinned).length - before.filter((b) => b.pinned).length;
  const leftover = [...pool.values()].reduce((a, n) => a + n, 0);
  return { kept, moved: Math.max(0, leftover - Math.max(0, newlyPinned)), ids };
}

function describe(c: Change) {
  const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;
  if (c.moved === 0 && c.ids.size) {
    return `Added ${plural(c.ids.size, "block")}.`;
  }
  if (c.moved && !c.ids.size) return `Removed ${plural(c.moved, "block")}.`;
  return `Moved ${plural(c.moved, "block")}.`;
}

export default function Home() {
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [courses, setCourses] = useState<Course[]>([]);
  const [commitments, setCommitments] = useState<Commitment[]>([]);
  const [settings, setSettings] = useState<SettingsOut | null>(null);
  const [checkIn, setCheckIn] = useState<{ since: string | null; tasks: CheckInTask[] }>({
    since: null,
    tasks: [],
  });
  const [notice, setNotice] = useState<string | null>(null);
  // What the last reload changed, so a rebuild is visible rather than silent.
  const [change, setChange] = useState<Change | null>(null);
  const lastBlocks = useRef<Block[] | null>(null);
  const changeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    // Settings first: it creates the user if needed, so a brand-new visitor can
    // set a study window or add a commitment before uploading anything.
    // (No state is set before the first await: load runs from an effect.)
    try {
      const s = await getSettings();
      setError(null);
      setSettings(s);
      setCommitments(await getCommitments());
      setCheckIn(await getCheckIn());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
    try {
      const [schedule, asgs, crs] = await Promise.all([
        getSchedule(),
        getAssignments(),
        getCourses(),
      ]);
      if (lastBlocks.current) {
        const diff = diffPlans(lastBlocks.current, schedule.blocks);
        if (diff.moved || diff.ids.size) {
          setChange(diff);
          if (changeTimer.current) clearTimeout(changeTimer.current);
          changeTimer.current = setTimeout(() => setChange(null), 7000);
        }
      }
      lastBlocks.current = schedule.blocks;
      setBlocks(schedule.blocks);
      setAssignments(asgs);
      setCourses(crs);
    } catch (err) {
      // A 404 just means no upload yet -- that's the empty state, not a failure.
      const msg = err instanceof Error ? err.message : String(err);
      if (!msg.includes("No user")) setError(msg);
      setBlocks([]);
      setAssignments([]);
      setCourses([]);
    }
  }, []);

  useEffect(() => {
    // Initial fetch. load() only sets state after its awaits resolve, which the
    // rule can't see through the async call.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  // Optimistic: move the block locally, then persist. On failure, reload to the
  // server's truth rather than leaving the calendar lying.
  const commitBlock = useCallback(
    async (
      id: string,
      patch: { day?: string; start_time?: string; hours?: number },
    ) => {
      setBusy(true);
      setBlocks((prev) =>
        prev.map((b) => (b.id === id ? { ...b, ...patch, pinned: true } : b)),
      );
      try {
        await patchBlock(id, patch);
        await reschedule();
        await load();
      } catch (err) {
        // 409 = dropped onto another pinned block. Snap back to the server's truth.
        setError(err instanceof Error ? err.message : String(err));
        await load();
      } finally {
        setBusy(false);
      }
    },
    [load],
  );

  const removeCourse = useCallback(
    async (id: string) => {
      setBusy(true);
      try {
        await deleteCourse(id);
        await load();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [load],
  );

  const rebuild = useCallback(async (fresh = false) => {
    setBusy(true);
    try {
      await reschedule(fresh);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [load]);

  const courseOf = Object.fromEntries(
    assignments.map((a) => [a.id, a.course_code]),
  );
  const colorOf = taskColors(assignments);
  // Unconfirmed syllabus meetings wait in "Needs your input"; they aren't real
  // until checked, so the calendar and settings only see confirmed ones.
  const confirmed = commitments.filter((c) => c.confirmed);
  const totalHours = blocks.reduce((sum, b) => sum + b.hours, 0);
  const pinnedCount = blocks.filter((b) => b.pinned).length;

  return (
    <main className="mx-auto flex w-full max-w-[1600px] flex-col px-5 py-4 lg:h-dvh">
      <header className="mb-4 flex shrink-0 items-baseline gap-3 border-b border-line pb-3">
        <h1 className="text-xl font-semibold tracking-tight text-fg">
          Cadence
        </h1>
        <p className="truncate text-xs text-muted">
          Syllabi in, study schedule out — the schedule comes from a
          deterministic scheduler, not a language model.
        </p>
      </header>

      {error && (
        <p className="mb-3 shrink-0 rounded border border-red-500/40 bg-red-500/10 p-3 text-xs text-red-300">
          {error}
        </p>
      )}

      <div className="grid gap-5 lg:min-h-0 lg:flex-1 lg:grid-cols-[20rem_1fr]">
        <div className="space-y-4 lg:min-h-0 lg:overflow-y-auto lg:pr-1">
          {notice && (
            <p className="flex items-start justify-between gap-3 rounded-xl border border-accent/30 bg-accent/5 p-3 text-xs text-fg">
              {notice}
              <button
                onClick={() => setNotice(null)}
                className="shrink-0 text-muted hover:text-fg"
                aria-label="Dismiss"
              >
                ×
              </button>
            </p>
          )}
          <CheckInPanel
            since={checkIn.since}
            tasks={checkIn.tasks}
            onDone={(r) => {
              setNotice(describeCheckIn(r));
              void load();
            }}
          />
          <UploadPanel onDone={load} />
          <NeedsAttention
            assignments={assignments}
            meetings={commitments.filter((c) => !c.confirmed)}
            onChanged={load}
          />
          <TaskList
            assignments={assignments}
            colorOf={colorOf}
            onChanged={load}
          />
          <SettingsPanel
            settings={settings}
            commitments={confirmed}
            courses={courses}
            onChanged={load}
            setBusy={setBusy}
          />

          {courses.length > 0 && (
            <section className="rounded-xl border border-line bg-surface p-5">
              <h2 className="text-sm font-semibold text-fg">Courses</h2>
              <ul className="mt-2 space-y-1.5">
                {courses.map((c) => (
                  <li
                    key={c.id}
                    className="flex items-start justify-between gap-3 text-xs text-fg/85"
                  >
                    <span>
                      <span className="font-medium">{c.code}</span> — {c.title}
                      <span className="block text-muted">
                        {c.assignments} item{c.assignments === 1 ? "" : "s"}
                        {c.term && ` · ${c.term}`}
                      </span>
                    </span>
                    <button
                      onClick={() => removeCourse(c.id)}
                      disabled={busy}
                      className="shrink-0 rounded px-1.5 py-0.5 text-[11px] text-muted hover:bg-raised hover:text-red-300 disabled:opacity-40"
                      aria-label={`Remove ${c.code}`}
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {blocks.length > 0 && (
            <section className="rounded-xl border border-line bg-surface p-5 text-xs text-muted">
              <dl className="grid grid-cols-3 gap-2">
                <div>
                  <dt className="text-muted">Blocks</dt>
                  <dd className="mt-0.5 font-mono text-lg font-medium text-fg tabular-nums">
                    {blocks.length}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted">Hours</dt>
                  <dd className="mt-0.5 font-mono text-lg font-medium text-fg tabular-nums">
                    {totalHours.toFixed(1)}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted">Pinned</dt>
                  <dd className="mt-0.5 font-mono text-lg font-medium text-fg tabular-nums">
                    {pinnedCount}
                  </dd>
                </div>
              </dl>
              <button
                onClick={() => rebuild()}
                disabled={busy}
                className="mt-3 w-full rounded border border-line bg-raised px-3 py-1.5 text-xs font-medium text-fg hover:border-accent/50 disabled:opacity-50"
              >
                {busy ? "Rebuilding…" : "Rebuild schedule"}
              </button>
              <a
                href={calendarExportUrl()}
                download="cadence.ics"
                className="mt-2 block w-full rounded border border-line px-3 py-1.5 text-center text-xs font-medium text-fg/90 hover:border-accent/50"
              >
                Export to calendar (.ics)
              </a>
              <p className="mt-1 text-[11px] text-muted">
                Keeps every block that still fits and moves only what has to.{" "}
                <button
                  onClick={() => rebuild(true)}
                  disabled={busy}
                  className="text-accent/80 underline-offset-2 hover:text-accent hover:underline disabled:opacity-50"
                >
                  Start fresh
                </button>{" "}
                to re-spread everything (pinned blocks still stay).
              </p>
            </section>
          )}
        </div>

        <div className="relative flex h-[80dvh] min-h-0 flex-col lg:h-auto">
          {change && (
            <div
              role="status"
              className="pointer-events-none absolute bottom-10 left-1/2 z-20 -translate-x-1/2 rounded-full border border-line bg-raised/95 px-3.5 py-1.5 text-xs text-fg shadow-lg shadow-black/40"
            >
              <span className="mr-1.5 inline-block h-1.5 w-1.5 translate-y-[-1px] rounded-full bg-accent align-middle" />
              {describe(change)}
            </div>
          )}
          <ScheduleCalendar
            changed={change?.ids}
            blocks={blocks}
            commitments={confirmed}
            courseOf={courseOf}
            colorOf={colorOf}
            busy={busy}
            onMove={(id, start) =>
              commitBlock(id, {
                day: toDateStr(start),
                start_time: toTimeStr(start),
              })
            }
            onResize={(id, hours) =>
              commitBlock(id, { hours: Math.max(0.25, hours) })
            }
          />
        </div>
      </div>
    </main>
  );
}
