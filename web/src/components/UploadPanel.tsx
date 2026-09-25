"use client";

import { useRef, useState } from "react";

import { uploadSyllabusStream, type RescheduleSummary } from "@/lib/api";

type Line = { text: string; kind: "step" | "note" | "error" };

export default function UploadPanel({ onDone }: { onDone: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [termStart, setTermStart] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [running, setRunning] = useState(false);
  const [summary, setSummary] = useState<RescheduleSummary | null>(null);

  const say = (text: string, kind: Line["kind"] = "step") =>
    setLines((prev) => [...prev, { text, kind }]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) return;

    setLines([]);
    setSummary(null);
    setRunning(true);

    try {
      await uploadSyllabusStream(file, termStart || null, (ev) => {
        switch (ev.event) {
          case "start":
            say(`Reading ${file.name}`);
            break;
          case "node":
            ev.data.trace.forEach((t) => say(t));
            break;
          case "persisted":
            say(`Saved ${ev.data.courses.join(", ")}`, "note");
            break;
          case "scheduled":
            setSummary(ev.data);
            say(
              `Scheduled ${ev.data.scheduled} assignment(s) into ${ev.data.blocks} block(s)`,
            );
            break;
          case "error":
            // The response was a 200, so this never reaches the catch below.
            say(ev.data.detail, "error");
            break;
        }
      });
      onDone();
    } catch (err) {
      say(err instanceof Error ? err.message : String(err), "error");
    } finally {
      setRunning(false);
    }
  }

  return (
    <section className="rounded-xl border border-line bg-surface p-5">
      <h2 className="text-sm font-semibold text-fg">Upload a syllabus</h2>
      <p className="mt-1 text-xs text-muted">PDF or Word. Scanned documents won&apos;t work yet.</p>

      <form onSubmit={submit} className="mt-3 space-y-3">
        <input
          ref={fileRef}
          id="syllabus-file"
          type="file"
          accept=".pdf,.docx"
          required
          className="block w-full text-xs text-fg/85 file:mr-3 file:rounded file:border file:border-line file:bg-raised file:px-3 file:py-1.5 file:text-xs file:text-fg"
        />
        <div>
          <label htmlFor="term-start" className="block text-xs font-medium text-fg/85">
            First day of term
          </label>
          <p className="text-[11px] text-muted">
            Needed to turn &quot;Week 4&quot; into a real date.
          </p>
          <input
            id="term-start"
            type="date"
            value={termStart}
            onChange={(e) => setTermStart(e.target.value)}
            className="mt-1 rounded border border-line bg-raised px-2 py-1 text-xs text-fg"
          />
        </div>
        <button
          type="submit"
          disabled={running}
          className="rounded bg-accent px-3 py-1.5 text-xs font-semibold text-ground disabled:opacity-50"
        >
          {running ? "Working…" : "Upload"}
        </button>
      </form>

      {lines.length > 0 && (
        <ol className="mt-4 space-y-1 border-t border-line pt-3 font-mono text-[11px]">
          {lines.map((l, i) => (
            <li
              key={i}
              className={
                l.kind === "error"
                  ? "text-red-400"
                  : l.kind === "note"
                    ? "text-muted"
                    : "text-fg/85"
              }
            >
              {l.text}
            </li>
          ))}
          {running && <li className="text-faint">…</li>}
        </ol>
      )}

      {summary && (summary.needs_date.length > 0 || summary.categories.length > 0) && (
        <p className="mt-3 text-xs text-warn">
          {summary.needs_date.length > 0 &&
            `${summary.needs_date.length} item(s) need a date. `}
          {summary.categories.length > 0 &&
            `${summary.categories.length} grading categor${summary.categories.length === 1 ? "y" : "ies"} found.`}
        </p>
      )}
    </section>
  );
}
