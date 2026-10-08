"use client";

import { useRef, useState } from "react";
import { format } from "date-fns";

import {
  createCommitmentsBulk,
  previewCalendarImport,
  type ImportCandidate,
  type NewCommitment,
} from "@/lib/api";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const clock = (t: string) => format(new Date(`1970-01-01T${t}`), "h:mmaaa");
const day = (d: string) => format(new Date(`${d}T00:00`), "EEE MMM d");

/**
 * Bring work shifts, appointments and other busy time in from Google, Apple or
 * Outlook: export the calendar as .ics, pick it here, tick what to keep.
 * Weekly repeats become one commitment per weekday; the rest are one-offs.
 */
export default function ImportCalendar({ onImported }: { onImported: () => Promise<void> | void }) {
  const input = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<{
    candidates: ImportCandidate[];
    skipped: Record<string, number>;
  } | null>(null);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function choose(file: File) {
    setBusy(true);
    setError(null);
    try {
      const p = await previewCalendarImport(file);
      setPreview(p);
      // Weekly ones and anything new are ticked; duplicates are not.
      setPicked(new Set(p.candidates.flatMap((c, i) => (c.exists ? [] : [i]))));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  async function save() {
    if (!preview) return;
    setBusy(true);
    setError(null);
    try {
      const items: NewCommitment[] = preview.candidates
        .filter((_, i) => picked.has(i))
        .map((c) => ({
          title: c.title,
          kind: c.kind,
          start_time: c.start_time,
          end_time: c.end_time,
          ...(c.weekday !== null ? { weekday: c.weekday } : {}),
          ...(c.on_date ? { on_date: c.on_date } : {}),
          ...(c.starts_on ? { starts_on: c.starts_on } : {}),
          ...(c.ends_on ? { ends_on: c.ends_on } : {}),
        }));
      await createCommitmentsBulk(items);
      setPreview(null);
      await onImported();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const toggle = (i: number) => {
    const next = new Set(picked);
    if (next.has(i)) next.delete(i);
    else next.add(i);
    setPicked(next);
  };

  const skippedText = preview
    ? Object.entries(preview.skipped).map(([why, n]) => `${n} ${why}`).join(", ")
    : "";

  return (
    <div className="mt-3">
      <input
        ref={input}
        type="file"
        accept=".ics,text/calendar"
        className="hidden"
        onChange={(e) => e.target.files?.[0] && choose(e.target.files[0])}
      />
      {!preview && (
        <button
          onClick={() => input.current?.click()}
          disabled={busy}
          className="w-full rounded border border-dashed border-line px-3 py-1.5 text-xs text-muted hover:border-accent/50 hover:text-fg disabled:opacity-50"
        >
          {busy ? "Reading calendar…" : "Import from calendar (.ics)"}
        </button>
      )}

      {preview && (
        <div className="rounded-lg border border-line bg-raised/40 p-3">
          <p className="text-xs font-medium text-fg">
            {preview.candidates.length
              ? `Found ${preview.candidates.length} busy time${preview.candidates.length === 1 ? "" : "s"}`
              : "Nothing to import in the next four months"}
          </p>
          <p className="mt-0.5 text-[10.5px] text-faint">
            Untick anything you can study through.
            {skippedText && ` Skipped: ${skippedText}.`}
          </p>
          {preview.candidates.length > 0 && (
            <ul className="mt-2 max-h-64 space-y-1 overflow-y-auto pr-1">
              {preview.candidates.map((c, i) => (
                <li key={i}>
                  <label className="flex items-center gap-2 text-xs">
                    <input type="checkbox" checked={picked.has(i)} onChange={() => toggle(i)} />
                    <span className="min-w-0 flex-1 truncate text-fg/90" title={c.title}>
                      {c.title}
                      {c.exists && <span className="text-faint"> · already added</span>}
                    </span>
                    <span className="shrink-0 font-mono text-[10.5px] text-muted">
                      {c.weekday !== null ? `every ${DAYS[c.weekday]}` : c.on_date && day(c.on_date)}{" "}
                      {clock(c.start_time)}–{clock(c.end_time)}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
          {error && <p className="mt-2 text-[11px] text-red-300">{error}</p>}
          <div className="mt-3 flex gap-2">
            <button
              onClick={save}
              disabled={busy || picked.size === 0}
              className="flex-1 rounded bg-accent px-3 py-1.5 text-xs font-medium text-ground disabled:opacity-40"
            >
              {busy ? "Adding…" : `Add ${picked.size}`}
            </button>
            <button
              onClick={() => setPreview(null)}
              className="rounded px-3 py-1.5 text-xs text-muted hover:text-fg"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
      {!preview && error && <p className="mt-2 text-[11px] text-red-300">{error}</p>}
    </div>
  );
}
