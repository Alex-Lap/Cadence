"use client";

import { useState } from "react";
import { format } from "date-fns";

import ImportCalendar from "@/components/ImportCalendar";
import TimeSelect from "@/components/TimeSelect";
import {
  createCommitment,
  deleteCommitment,
  putSettings,
  type Commitment,
  type CommitmentKind,
  type Course,
  type SettingsOut,
} from "@/lib/api";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const DAY_CHIPS = ["M", "Tu", "W", "Th", "F", "Sa", "Su"];
const KINDS: { value: CommitmentKind; label: string }[] = [
  { value: "class", label: "Class" },
  { value: "work", label: "Work" },
  { value: "other", label: "Other" },
];

/** "18:30:00" -> "6:30pm" */
function clock(t: string) {
  return format(new Date(`1970-01-01T${t}`), "h:mmaaa");
}

/** "18:30:00" -> "18:30", the shape <input type="time"> wants. */
const hhmm = (t: string | null) => (t ? t.slice(0, 5) : "");

const inputCls =
  "w-full rounded border border-line bg-raised px-2 py-1 text-xs text-fg focus:border-accent/60 focus:outline-none";

/**
 * When you can study, and what's already taking that time. The scheduler only
 * places work inside the study window and around these commitments.
 */
export default function SettingsPanel({
  settings,
  commitments,
  courses,
  onChanged,
  setBusy,
}: {
  settings: SettingsOut | null;
  commitments: Commitment[];
  courses: Course[];
  onChanged: () => Promise<void> | void;
  setBusy: (b: boolean) => void;
}) {
  const [error, setError] = useState<string | null>(null);

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    setBusy(true);
    try {
      await fn();
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl border border-line bg-surface p-5">
      <h2 className="text-sm font-semibold text-fg">Availability</h2>
      <p className="mt-0.5 text-[11px] text-muted">
        Study is planned inside your window and around everything below.
      </p>

      <WindowForm
        // Remount when the saved values change, so the inputs re-seed from them.
        key={`${settings?.study_start}|${settings?.study_end}|${settings?.max_hours_per_day}`}
        settings={settings}
        onSave={(s) => run(() => putSettings(s))}
      />

      <h3 className="mt-5 text-xs font-semibold text-fg">Commitments</h3>
      {commitments.length === 0 ? (
        <p className="mt-1 text-[11px] text-muted">
          None yet. Add classes, work shifts or anything else you can&apos;t
          study through.
        </p>
      ) : (
        <ul className="mt-2 space-y-1">
          {commitments.map((c) => (
            <li key={c.id} className="flex items-center gap-2 text-xs">
              <span
                className={`h-2.5 w-2.5 shrink-0 rounded-sm ${c.kind === "off" ? "bg-warn/60" : "bg-faint"}`}
              />
              <span className="min-w-0 flex-1 truncate text-fg/90" title={c.title}>
                {c.title}
                {c.course_code && (
                  <span className="text-muted"> · {c.course_code}</span>
                )}
              </span>
              <span className="shrink-0 font-mono text-[10.5px] text-muted">
                {c.kind === "off" ? (
                  dayRange(c.on_date, c.ends_on)
                ) : (
                  <>
                    {c.weekday !== null
                      ? DAYS[c.weekday]
                      : c.on_date && format(new Date(`${c.on_date}T00:00`), "MMM d")}{" "}
                    {clock(c.start_time)}–{clock(c.end_time)}
                  </>
                )}
              </span>
              <button
                onClick={() => run(() => deleteCommitment(c.id))}
                className="shrink-0 rounded px-1 text-[13px] leading-none text-muted hover:bg-raised hover:text-red-300"
                aria-label={`Remove ${c.title}`}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}

      <AddDayOff
        onAdd={(row) => run(() => createCommitment(row))}
      />

      <ImportCalendar onImported={onChanged} />

      <AddCommitment
        courses={courses}
        existing={commitments}
        onAdd={(rows) =>
          // One row per weekday; each POST rebuilds, so send them in order.
          run(async () => {
            for (const r of rows) await createCommitment(r);
          })
        }
      />

      {error && <p className="mt-2 text-xs text-red-300">{error}</p>}
    </section>
  );
}

function WindowForm({
  settings,
  onSave,
}: {
  settings: SettingsOut | null;
  onSave: (s: {
    study_start: string | null;
    study_end: string | null;
    max_hours_per_day: number | null;
  }) => void;
}) {
  const [start, setStart] = useState(hhmm(settings?.study_start ?? null));
  const [end, setEnd] = useState(hhmm(settings?.study_end ?? null));
  const [hours, setHours] = useState(settings?.max_hours_per_day?.toString() ?? "");

  const eff = settings?.effective;
  const dirty =
    start !== hhmm(settings?.study_start ?? null) ||
    end !== hhmm(settings?.study_end ?? null) ||
    hours !== (settings?.max_hours_per_day?.toString() ?? "");

  return (
    <form
      className="mt-3 grid grid-cols-3 gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        onSave({
          study_start: start || null,
          study_end: end || null,
          max_hours_per_day: hours ? Number(hours) : null,
        });
      }}
    >
      <div className="col-span-3 flex flex-wrap items-end gap-x-4 gap-y-2 text-[11px] text-muted">
        <div>
          From
          <div className="mt-1">
            <TimeSelect label="Study from" value={start} onChange={setStart} allowEmpty />
          </div>
        </div>
        <div>
          Until
          <div className="mt-1">
            <TimeSelect label="Study until" value={end} onChange={setEnd} allowEmpty />
          </div>
        </div>
      </div>
      <label className="col-span-3 flex flex-col text-[11px] text-muted">
        Max hours a day
        <input
          type="number"
          min={0.25}
          max={24}
          step={0.25}
          value={hours}
          placeholder={eff?.max_hours_per_day?.toString()}
          onChange={(e) => setHours(e.target.value)}
          className={`${inputCls} mt-1 !w-24`}
        />
      </label>
      <p className="col-span-3 text-[10.5px] text-faint">
        {start || end || hours
          ? "Blank fields use the default."
          : `Default: from ${clock(eff?.study_start ?? "18:00:00")}, up to ${eff?.max_hours_per_day ?? 4}h a day.`}
      </p>
      {dirty && (
        <button
          type="submit"
          className="col-span-3 rounded border border-accent/50 bg-accent/10 px-3 py-1.5 text-xs font-medium text-accent hover:bg-accent/20"
        >
          Save and rebuild
        </button>
      )}
    </form>
  );
}

/** "Nov 25" or "Nov 25 – 29" or "Nov 28 – Dec 2". */
function dayRange(first: string | null, last: string | null) {
  if (!first) return "";
  const a = new Date(`${first}T00:00`);
  if (!last || last === first) return format(a, "EEE MMM d");
  const b = new Date(`${last}T00:00`);
  return a.getMonth() === b.getMonth()
    ? `${format(a, "MMM d")} – ${format(b, "d")}`
    : `${format(a, "MMM d")} – ${format(b, "MMM d")}`;
}

/** A day or a stretch of days with no study: a holiday, a trip, a break. */
function AddDayOff({
  onAdd,
}: {
  onAdd: (row: {
    title: string;
    kind: CommitmentKind;
    on_date: string;
    ends_on?: string;
    start_time: string;
    end_time: string;
  }) => void;
}) {
  const [open, setOpen] = useState(false);
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [title, setTitle] = useState("");

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="mt-3 w-full rounded border border-dashed border-line px-3 py-1.5 text-xs text-muted hover:border-accent/50 hover:text-fg"
      >
        + Day off
      </button>
    );
  }

  const valid = !!first && (!last || last >= first);
  function reset() {
    setOpen(false);
    setFirst("");
    setLast("");
    setTitle("");
  }

  return (
    <form
      className="mt-3 space-y-2 rounded-lg border border-line bg-raised/40 p-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (!valid) return;
        onAdd({
          title: title.trim() || "Day off",
          kind: "off",
          on_date: first,
          ...(last && last !== first ? { ends_on: last } : {}),
          start_time: "00:00",
          end_time: "23:59",
        });
        reset();
      }}
    >
      <label className="block text-[11px] text-muted">
        Name
        <input
          value={title}
          placeholder="Day off"
          onChange={(e) => setTitle(e.target.value)}
          className={`${inputCls} mt-1`}
        />
      </label>
      <div className="flex gap-2 text-[11px] text-muted">
        <label className="flex-1">
          From
          <input
            type="date"
            value={first}
            onChange={(e) => setFirst(e.target.value)}
            className={`${inputCls} mt-1`}
            aria-label="First day off"
          />
        </label>
        <label className="flex-1">
          Through <span className="text-faint">(optional)</span>
          <input
            type="date"
            value={last}
            min={first || undefined}
            onChange={(e) => setLast(e.target.value)}
            className={`${inputCls} mt-1`}
            aria-label="Last day off"
          />
        </label>
      </div>
      {first && last && last < first && (
        <p className="text-[11px] text-red-300">The last day is before the first.</p>
      )}
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={!valid}
          className="flex-1 rounded bg-accent px-3 py-1.5 text-xs font-medium text-ground disabled:opacity-40"
        >
          Add
        </button>
        <button
          type="button"
          onClick={reset}
          className="rounded px-3 py-1.5 text-xs text-muted hover:text-fg"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

/** "Class 1", "Class 2", ...: the first number no existing commitment uses. */
function nextName(base: string, existing: Commitment[]) {
  const taken = new Set(existing.map((c) => c.title.toLowerCase()));
  let n = 1;
  while (taken.has(`${base} ${n}`.toLowerCase())) n++;
  return `${base} ${n}`;
}

const KIND_NAME: Record<CommitmentKind, string> = {
  class: "Class",
  work: "Work",
  other: "Commitment",
  off: "Day off",
};

function AddCommitment({
  courses,
  existing,
  onAdd,
}: {
  courses: Course[];
  existing: Commitment[];
  onAdd: (
    rows: {
      title: string;
      kind: CommitmentKind;
      weekday?: number;
      on_date?: string;
      start_time: string;
      end_time: string;
      course_id?: string;
    }[],
  ) => void;
}) {
  const [open, setOpen] = useState(false);
  // Empty means "use the suggested name"; typing anything overrides it.
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<CommitmentKind>("class");
  const [repeat, setRepeat] = useState<"weekly" | "once">("weekly");
  const [days, setDays] = useState<number[]>([]);
  const [date, setDate] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  // Until the user picks an end time, it follows the start, an hour later.
  const [endTouched, setEndTouched] = useState(false);
  const [courseId, setCourseId] = useState("");

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="mt-3 w-full rounded border border-dashed border-line px-3 py-1.5 text-xs text-muted hover:border-accent/50 hover:text-fg"
      >
        + Add commitment
      </button>
    );
  }

  const course = courses.find((c) => c.id === courseId);
  const suggested =
    kind === "class" && course ? course.code : nextName(KIND_NAME[kind], existing);
  const name = title.trim() || suggested;

  const valid =
    name &&
    start &&
    end &&
    end > start &&
    (repeat === "weekly" ? days.length > 0 : !!date);

  function reset() {
    setOpen(false);
    setTitle("");
    setDays([]);
    setDate("");
    setStart("");
    setEnd("");
    setEndTouched(false);
    setCourseId("");
  }

  return (
    <form
      className="mt-3 space-y-2 rounded-lg border border-line bg-raised/40 p-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (!valid) return;
        const base = {
          title: name,
          kind,
          start_time: start,
          end_time: end,
          ...(courseId ? { course_id: courseId } : {}),
        };
        onAdd(
          repeat === "weekly"
            ? days.map((d) => ({ ...base, weekday: d }))
            : [{ ...base, on_date: date }],
        );
        reset();
      }}
    >
      <div className="flex gap-2">
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as CommitmentKind)}
          className={inputCls}
        >
          {KINDS.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label}
            </option>
          ))}
        </select>
        {kind === "class" && courses.length > 0 && (
          <select
            value={courseId}
            onChange={(e) => setCourseId(e.target.value)}
            className={inputCls}
          >
            <option value="">No course</option>
            {courses.map((c) => (
              <option key={c.id} value={c.id}>
                {c.code}
              </option>
            ))}
          </select>
        )}
      </div>

      <label className="block text-[11px] text-muted">
        Name
        <input
          // Shows the suggested name until the user types their own; clearing
          // the field goes back to the suggestion.
          value={title || suggested}
          onChange={(e) => setTitle(e.target.value === suggested ? "" : e.target.value)}
          onFocus={(e) => e.target.select()}
          className={`${inputCls} mt-1 ${title ? "" : "text-fg/70"}`}
        />
      </label>

      <div className="flex gap-1 text-[11px]">
        {(["weekly", "once"] as const).map((r) => (
          <button
            key={r}
            type="button"
            onClick={() => setRepeat(r)}
            className={`flex-1 rounded px-2 py-1 ${repeat === r ? "bg-accent/15 text-accent" : "text-muted hover:text-fg"}`}
          >
            {r === "weekly" ? "Every week" : "One time"}
          </button>
        ))}
      </div>

      {repeat === "weekly" ? (
        <div className="flex gap-1">
          {DAYS.map((d, i) => {
            const on = days.includes(i);
            return (
              <button
                key={d}
                type="button"
                onClick={() =>
                  setDays(on ? days.filter((x) => x !== i) : [...days, i].sort())
                }
                className={`flex-1 rounded py-1 text-[10.5px] ${on ? "bg-accent text-ground" : "bg-raised text-muted hover:text-fg"}`}
                aria-pressed={on}
              >
                {DAY_CHIPS[i]}
              </button>
            );
          })}
        </div>
      ) : (
        <input
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          className={inputCls}
        />
      )}

      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5 text-[11px] text-muted">
        <TimeSelect
          label="Starts"
          value={start}
          onChange={(v) => {
            setStart(v);
            if (v && !endTouched) {
              const [h, m] = v.split(":").map(Number);
              const t = Math.min(h * 60 + m + 60, 23 * 60 + 45);
              setEnd(`${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`);
            }
          }}
        />
        to
        <TimeSelect
          label="Ends"
          value={end}
          onChange={(v) => {
            setEnd(v);
            setEndTouched(true);
          }}
        />
      </div>
      {start && end && end <= start && (
        <p className="text-[11px] text-red-300">Ends before it starts.</p>
      )}

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={!valid}
          className="flex-1 rounded bg-accent px-3 py-1.5 text-xs font-medium text-ground disabled:opacity-40"
        >
          Add
        </button>
        <button
          type="button"
          onClick={reset}
          className="rounded px-3 py-1.5 text-xs text-muted hover:text-fg"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
