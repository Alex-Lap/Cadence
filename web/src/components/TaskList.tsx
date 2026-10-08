"use client";

import { useEffect, useRef, useState } from "react";
import { format } from "date-fns";

import {
  createAssignment,
  deleteAssignment,
  dueDay,
  patchAssignment,
  reschedule,
  type Assignment,
  type Course,
} from "@/lib/api";
import { TASK_COLORS } from "@/lib/colors";

const inputCls =
  "w-full rounded border border-line bg-raised px-2 py-1 text-xs text-fg focus:border-accent/60 focus:outline-none";

const shortDay = (iso: string | null) =>
  iso ? format(new Date(`${dueDay(iso)}T00:00`), "MMM d") : "";

/**
 * Every schedulable task. Click a swatch to change its colour; click a task to
 * edit its name, due date, hours or weight, mark it finished, or delete it.
 * "+ Add task" covers anything the syllabus missed or that isn't from a course.
 */
export default function TaskList({
  assignments,
  courses,
  colorOf,
  onChanged,
}: {
  assignments: Assignment[];
  courses: Course[];
  colorOf: Record<string, string>;
  onChanged: () => void;
}) {
  const [colorFor, setColorFor] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const tasks = assignments
    .filter((a) => !a.is_category && !a.is_participation && a.due_at)
    .sort((a, b) => Number(a.done) - Number(b.done) || dueDay(a.due_at).localeCompare(dueDay(b.due_at)));

  async function setColor(id: string, color: string | null) {
    setError(null);
    try {
      await patchAssignment(id, { color });
      setColorFor(null);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <section className="rounded-xl border border-line bg-surface p-5">
      <h2 className="text-sm font-semibold text-fg">Tasks</h2>
      <p className="mt-0.5 text-[11px] text-muted">
        Click a task to edit it, or a colour to recolour it.
      </p>
      {tasks.length > 0 && (
        <ul className="mt-3 space-y-1">
          {tasks.map((a) => (
            <li key={a.id} className="relative text-xs">
              <div className="flex items-center gap-2.5">
                <button
                  onClick={() => setColorFor(colorFor === a.id ? null : a.id)}
                  className="h-4 w-4 shrink-0 rounded-full ring-1 ring-white/10 transition hover:scale-110 focus-visible:outline-2 focus-visible:outline-accent"
                  style={{ background: colorOf[a.id], opacity: a.done ? 0.4 : 1 }}
                  aria-label={`Change colour for ${a.title}`}
                  aria-expanded={colorFor === a.id}
                />
                <button
                  onClick={() => setEditing(editing === a.id ? null : a.id)}
                  className={`min-w-0 flex-1 truncate text-left hover:text-accent ${a.done ? "text-muted line-through" : "text-fg/90"}`}
                  title={a.title}
                  aria-expanded={editing === a.id}
                >
                  {a.title}
                </button>
                <span className="shrink-0 font-mono text-[10.5px] text-muted">
                  {a.done ? "done" : shortDay(a.due_at)}
                </span>
              </div>
              {colorFor === a.id && (
                <ColorPicker
                  current={colorOf[a.id]}
                  custom={a.color}
                  onPick={(c) => setColor(a.id, c)}
                  onClose={() => setColorFor(null)}
                />
              )}
              {editing === a.id && (
                <EditTask
                  task={a}
                  onClose={() => setEditing(null)}
                  onSaved={() => {
                    setEditing(null);
                    onChanged();
                  }}
                />
              )}
            </li>
          ))}
        </ul>
      )}
      <AddTask courses={courses} onAdded={onChanged} />
      {error && <p className="mt-2 text-xs text-red-300">{error}</p>}
    </section>
  );
}

function EditTask({
  task,
  onClose,
  onSaved,
}: {
  task: Assignment;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [title, setTitle] = useState(task.title);
  const [due, setDue] = useState(dueDay(task.due_at));
  const [hours, setHours] = useState(String(task.estimated_hours));
  const [weight, setWeight] = useState(
    task.weight != null ? String(Number((task.weight * 100).toFixed(2))) : "",
  );
  const [done, setDone] = useState(task.done);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const valid = title.trim() && due && Number(hours) > 0 && (weight === "" || (Number(weight) >= 0 && Number(weight) <= 100));

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  const save = () =>
    run(async () => {
      await patchAssignment(task.id, {
        title: title.trim(),
        due_at: `${due}T00:00:00`,
        estimated_hours: Number(hours),
        weight: weight === "" ? null : Number(weight) / 100,
        done,
      });
      await reschedule(); // PATCH alone doesn't rebuild
    });

  return (
    <form
      className="mt-2 space-y-2 rounded-lg border border-line bg-raised/40 p-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (valid) void save();
      }}
    >
      <label className="block text-[11px] text-muted">
        Name
        <input value={title} onChange={(e) => setTitle(e.target.value)} className={`${inputCls} mt-1`} />
      </label>
      <div className="grid grid-cols-3 gap-2 text-[11px] text-muted">
        <label>
          Due
          <input type="date" value={due} onChange={(e) => setDue(e.target.value)} className={`${inputCls} mt-1`} />
        </label>
        <label>
          Hours
          <input
            type="number" min={0.25} step={0.25} value={hours}
            onChange={(e) => setHours(e.target.value)} className={`${inputCls} mt-1`}
          />
        </label>
        <label>
          Weight %
          <input
            type="number" min={0} max={100} step={0.5} value={weight} placeholder="—"
            onChange={(e) => setWeight(e.target.value)} className={`${inputCls} mt-1`}
          />
        </label>
      </div>
      <p className="text-[10.5px] text-faint">
        {task.course_code}
        {task.completed_hours > 0 && ` · ${Number(task.completed_hours.toFixed(2))}h logged so far`}
      </p>
      <label className="flex items-center gap-2 text-[11px] text-fg/90">
        <input type="checkbox" checked={done} onChange={(e) => setDone(e.target.checked)} />
        Finished (stop scheduling it)
      </label>
      {error && <p className="text-[11px] text-red-300">{error}</p>}
      <div className="flex items-center gap-2">
        <button
          type="submit" disabled={busy || !valid}
          className="rounded bg-accent px-3 py-1.5 text-xs font-medium text-ground disabled:opacity-40"
        >
          {busy ? "Saving…" : "Save"}
        </button>
        <button type="button" onClick={onClose} className="rounded px-2 py-1.5 text-xs text-muted hover:text-fg">
          Cancel
        </button>
        <span className="flex-1" />
        {confirmDelete ? (
          <>
            <span className="text-[11px] text-muted">Delete it?</span>
            <button
              type="button" disabled={busy}
              onClick={() => run(() => deleteAssignment(task.id))}
              className="rounded px-2 py-1.5 text-xs font-medium text-red-300 hover:bg-red-500/10"
            >
              Yes, delete
            </button>
            <button type="button" onClick={() => setConfirmDelete(false)} className="text-xs text-muted hover:text-fg">
              No
            </button>
          </>
        ) : (
          <button
            type="button" onClick={() => setConfirmDelete(true)}
            className="rounded px-2 py-1.5 text-xs text-muted hover:text-red-300"
          >
            Delete
          </button>
        )}
      </div>
    </form>
  );
}

function AddTask({ courses, onAdded }: { courses: Course[]; onAdded: () => void }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [courseId, setCourseId] = useState("");
  const [due, setDue] = useState("");
  const [hours, setHours] = useState("2");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="mt-3 w-full rounded border border-dashed border-line px-3 py-1.5 text-xs text-muted hover:border-accent/50 hover:text-fg"
      >
        + Add task
      </button>
    );
  }

  const valid = title.trim() && due && Number(hours) > 0;
  const choices = courses.filter((c) => c.code !== "OTHER");

  function reset() {
    setOpen(false);
    setTitle("");
    setDue("");
    setHours("2");
    setError(null);
  }

  return (
    <form
      className="mt-3 space-y-2 rounded-lg border border-line bg-raised/40 p-3"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!valid) return;
        setBusy(true);
        setError(null);
        try {
          await createAssignment({
            title: title.trim(),
            ...(courseId ? { course_id: courseId } : {}),
            due_at: `${due}T00:00:00`,
            estimated_hours: Number(hours),
          });
          reset();
          onAdded();
        } catch (err) {
          setError(err instanceof Error ? err.message : String(err));
        } finally {
          setBusy(false);
        }
      }}
    >
      <input
        autoFocus value={title} onChange={(e) => setTitle(e.target.value)}
        placeholder="Task name" aria-label="Task name" className={inputCls}
      />
      <div className="grid grid-cols-3 gap-2 text-[11px] text-muted">
        <label className="col-span-3">
          Course
          <select value={courseId} onChange={(e) => setCourseId(e.target.value)} className={`${inputCls} mt-1`}>
            <option value="">Other (not a course)</option>
            {choices.map((c) => (
              <option key={c.id} value={c.id}>{c.code}</option>
            ))}
          </select>
        </label>
        <label className="col-span-2">
          Due
          <input type="date" value={due} onChange={(e) => setDue(e.target.value)} className={`${inputCls} mt-1`} />
        </label>
        <label>
          Hours
          <input
            type="number" min={0.25} step={0.25} value={hours}
            onChange={(e) => setHours(e.target.value)} className={`${inputCls} mt-1`}
          />
        </label>
      </div>
      {error && <p className="text-[11px] text-red-300">{error}</p>}
      <div className="flex gap-2">
        <button
          type="submit" disabled={busy || !valid}
          className="flex-1 rounded bg-accent px-3 py-1.5 text-xs font-medium text-ground disabled:opacity-40"
        >
          {busy ? "Adding…" : "Add and plan it"}
        </button>
        <button type="button" onClick={reset} className="rounded px-3 py-1.5 text-xs text-muted hover:text-fg">
          Cancel
        </button>
      </div>
    </form>
  );
}

function ColorPicker({
  current,
  custom,
  onPick,
  onClose,
}: {
  current: string;
  custom: string | null;
  onPick: (color: string | null) => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const away = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [onClose]);

  return (
    <div
      ref={ref}
      className="absolute left-0 top-6 z-40 w-52 rounded-lg border border-line bg-raised p-3 shadow-xl shadow-black/40"
    >
      <div className="grid grid-cols-8 gap-1.5">
        {TASK_COLORS.map((c) => (
          <button
            key={c}
            onClick={() => onPick(c)}
            className={`h-5 w-5 rounded-full transition hover:scale-110 ${
              c.toLowerCase() === current.toLowerCase()
                ? "ring-2 ring-fg ring-offset-2 ring-offset-raised"
                : ""
            }`}
            style={{ background: c }}
            aria-label={`Use ${c}`}
          />
        ))}
      </div>
      <div className="mt-3 flex items-center justify-between gap-2">
        <label className="flex cursor-pointer items-center gap-2 text-[11px] text-muted hover:text-fg">
          <input
            type="color"
            value={current}
            onChange={(e) => onPick(e.target.value)}
            className="h-5 w-6 cursor-pointer rounded border border-line bg-transparent p-0"
          />
          Custom
        </label>
        {custom && (
          <button
            onClick={() => onPick(null)}
            className="text-[11px] text-muted hover:text-fg"
          >
            Reset to automatic
          </button>
        )}
      </div>
    </div>
  );
}
