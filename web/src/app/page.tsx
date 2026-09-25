"use client";

import { useCallback, useEffect, useState } from "react";

import NeedsAttention from "@/components/NeedsAttention";
import TaskList from "@/components/TaskList";
import { taskColors } from "@/lib/colors";
import ScheduleCalendar from "@/components/ScheduleCalendar";
import UploadPanel from "@/components/UploadPanel";
import {
  deleteCourse,
  getAssignments,
  getCourses,
  getSchedule,
  patchBlock,
  reschedule,
  toDateStr,
  toTimeStr,
  type Assignment,
  type Block,
  type Course,
} from "@/lib/api";

export default function Home() {
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [courses, setCourses] = useState<Course[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [schedule, asgs, crs] = await Promise.all([
        getSchedule(),
        getAssignments(),
        getCourses(),
      ]);
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

  const rebuild = useCallback(async () => {
    setBusy(true);
    try {
      await reschedule();
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
          <UploadPanel onDone={load} />
          <NeedsAttention assignments={assignments} onChanged={load} />
          <TaskList
            assignments={assignments}
            colorOf={colorOf}
            onChanged={load}
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
                onClick={rebuild}
                disabled={busy}
                className="mt-3 w-full rounded border border-line bg-raised px-3 py-1.5 text-xs font-medium text-fg hover:border-accent/50 disabled:opacity-50"
              >
                {busy ? "Rebuilding…" : "Rebuild schedule"}
              </button>
              <p className="mt-1 text-[11px] text-muted">
                Keeps pinned blocks; replans everything else.
              </p>
            </section>
          )}
        </div>

        <div className="flex h-[80dvh] min-h-0 flex-col lg:h-auto">
          <ScheduleCalendar
            blocks={blocks}
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
