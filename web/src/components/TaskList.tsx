"use client";

import { useEffect, useRef, useState } from "react";
import { format } from "date-fns";

import { patchAssignment, type Assignment } from "@/lib/api";
import { TASK_COLORS } from "@/lib/colors";

/**
 * Every schedulable task with its calendar colour. Click a swatch to change it:
 * pick a preset, choose any colour, or go back to the automatic one.
 */
export default function TaskList({
  assignments,
  colorOf,
  onChanged,
}: {
  assignments: Assignment[];
  colorOf: Record<string, string>;
  onChanged: () => void;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const tasks = assignments
    .filter((a) => !a.is_category && a.due_at)
    .sort((a, b) => (a.due_at ?? "").localeCompare(b.due_at ?? ""));

  if (!tasks.length) return null;

  async function setColor(id: string, color: string | null) {
    setError(null);
    try {
      await patchAssignment(id, { color });
      setOpenId(null);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <section className="rounded-xl border border-line bg-surface p-5">
      <h2 className="text-sm font-semibold text-fg">Tasks</h2>
      <p className="mt-0.5 text-[11px] text-muted">
        Click a colour to change it on the calendar.
      </p>
      <ul className="mt-3 space-y-1">
        {tasks.map((a) => (
          <li key={a.id} className="relative flex items-center gap-2.5 text-xs">
            <button
              id={`color-${a.id}`}
              onClick={() => setOpenId(openId === a.id ? null : a.id)}
              className="h-4 w-4 shrink-0 rounded-full ring-1 ring-white/10 transition hover:scale-110 focus-visible:outline-2 focus-visible:outline-accent"
              style={{ background: colorOf[a.id] }}
              aria-label={`Change colour for ${a.title}`}
              aria-expanded={openId === a.id}
            />
            <span
              className="min-w-0 flex-1 truncate text-fg/90"
              title={a.title}
            >
              {a.title}
            </span>
            <span className="shrink-0 font-mono text-[10.5px] text-muted">
              {a.due_at && format(new Date(a.due_at), "MMM d")}
            </span>
            {openId === a.id && (
              <ColorPicker
                current={colorOf[a.id]}
                custom={a.color}
                onPick={(c) => setColor(a.id, c)}
                onClose={() => setOpenId(null)}
              />
            )}
          </li>
        ))}
      </ul>
      {error && <p className="mt-2 text-xs text-red-300">{error}</p>}
    </section>
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
