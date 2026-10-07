import { SignInButton, SignUpButton } from "@clerk/nextjs";

/**
 * What a signed-out visitor sees: what Cadence does, how, and a way in.
 * The calendar on the right is an illustration built from divs, not a
 * screenshot, so it stays sharp and on-palette at any size.
 */
export default function Landing() {
  return (
    <main className="mx-auto w-full max-w-6xl px-5 pb-20 sm:px-8">
      <nav className="flex items-center justify-between py-5">
        <span className="font-mono text-xs uppercase tracking-[0.2em] text-accent">Cadence</span>
        <SignInButton mode="modal">
          <button className="rounded-lg px-3 py-1.5 text-sm text-muted hover:text-fg">Sign in</button>
        </SignInButton>
      </nav>

      <section className="grid items-center gap-12 pt-10 lg:grid-cols-[1.05fr_1fr] lg:pt-16">
        <div>
          <h1 className="text-4xl font-semibold leading-[1.08] tracking-tight text-fg sm:text-5xl">
            Syllabi in.
            <br />
            Study schedule out.
          </h1>
          <p className="mt-5 max-w-xl text-base leading-relaxed text-muted sm:text-lg">
            Upload your syllabi. Cadence reads every deadline and grade weight, estimates the
            work, and plans study time around your classes and commitments. When something
            changes, it moves only what has to move.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <SignUpButton mode="modal">
              <button className="rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-ground hover:bg-accent/90">
                Get started free
              </button>
            </SignUpButton>
            <a
              href="#how"
              className="rounded-lg border border-line px-5 py-2.5 text-sm font-medium text-fg hover:border-accent/50"
            >
              How it works
            </a>
          </div>
        </div>
        <CalendarIllustration />
      </section>

      <section id="how" className="mt-28 scroll-mt-10">
        <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-muted">How it works</h2>
        <ol className="mt-6 grid gap-5 md:grid-cols-3">
          {STEPS.map((s, i) => (
            <li key={s.title} className="rounded-xl border border-line bg-surface p-6">
              <span className="font-mono text-xs text-accent">0{i + 1}</span>
              <h3 className="mt-2 text-base font-semibold text-fg">{s.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted">{s.body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="mt-20">
        <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-muted">
          Built to be trusted
        </h2>
        <div className="mt-6 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => (
            <div key={f.title} className="rounded-xl border border-line p-6">
              <h3 className="text-base font-semibold text-fg">{f.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted">{f.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="mt-20 rounded-2xl border border-line bg-surface px-6 py-8 sm:px-10">
        <h2 className="text-lg font-semibold text-fg">Measured, not assumed</h2>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          Every change to the syllabus reader is scored against a test set of nine syllabi:
          table schedules, week-based deadlines, prose-only syllabi, and ones with no dates at
          all.
        </p>
        <dl className="mt-6 grid grid-cols-2 gap-6 sm:grid-cols-4">
          {STATS.map((s) => (
            <div key={s.label}>
              <dt className="text-xs text-muted">{s.label}</dt>
              <dd className="mt-1 font-mono text-2xl font-medium text-fg tabular-nums">{s.value}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="mt-20 text-center">
        <h2 className="text-2xl font-semibold tracking-tight text-fg">
          Your semester, planned in a minute.
        </h2>
        <SignUpButton mode="modal">
          <button className="mt-6 rounded-lg bg-accent px-6 py-3 text-sm font-semibold text-ground hover:bg-accent/90">
            Get started free
          </button>
        </SignUpButton>
      </section>
    </main>
  );
}

const STEPS = [
  {
    title: "Upload your syllabi",
    body: "PDF or Word. Cadence finds every graded item, its weight, its due date or due week, and when the class meets.",
  },
  {
    title: "Check what it found",
    body: "Anything uncertain waits for you: an exam with no date, a class time that looks like a typo. Nothing is guessed silently.",
  },
  {
    title: "Get a plan that adapts",
    body: "Study blocks fill your free evenings before each deadline. Add a shift or a day off and only the affected blocks move.",
  },
];

const FEATURES = [
  {
    title: "A scheduler, not a chatbot",
    body: "AI reads the syllabus. The schedule itself comes from deterministic code, so the same inputs always give the same plan.",
  },
  {
    title: "Plans around your life",
    body: "Classes, work shifts and days off are blocked out. Study only lands in the window you choose.",
  },
  {
    title: "Small changes stay small",
    body: "Replanning keeps every block that still fits and tells you exactly what moved.",
  },
  {
    title: "Learns how long things take",
    body: "A weekly check-in records real hours. If a course keeps running long, its future estimates grow.",
  },
  {
    title: "Your calendar, your call",
    body: "Drag blocks to pin them. Export the plan to Google, Apple or Outlook calendar.",
  },
  {
    title: "No invented deadlines",
    body: "If a syllabus says an exam date is TBA, Cadence leaves it undated and asks, rather than making one up.",
  },
];

const STATS = [
  { label: "Graded items found", value: "65/65" },
  { label: "Due dates right", value: "48/48" },
  { label: "Class times found", value: "19/19" },
  { label: "Invented dates", value: "0" },
];

/* --------------------------------------------------------------- picture */

type Block = { day: number; start: number; len: number; label: string; hue?: string; busy?: boolean };

const BLOCKS: Block[] = [
  { day: 0, start: 1, len: 1.5, label: "CIS 6307", busy: true },
  { day: 2, start: 1, len: 1.5, label: "CIS 6307", busy: true },
  { day: 4, start: 1, len: 1.5, label: "CIS 6307", busy: true },
  { day: 1, start: 4.5, len: 2.5, label: "Shift", busy: true },
  { day: 0, start: 5, len: 2, label: "Work on Project 2", hue: "#6fcf97" },
  { day: 2, start: 5, len: 1.5, label: "Work on Project 2", hue: "#6fcf97" },
  { day: 3, start: 5, len: 2, label: "Study for Midterm", hue: "#8ab8ff" },
  { day: 4, start: 4.5, len: 1.5, label: "Read Chapter 7", hue: "#e5a663" },
  { day: 1, start: 7.25, len: 1, label: "Problem Set 3", hue: "#c49cf0" },
  { day: 3, start: 7.25, len: 1.25, label: "Problem Set 3", hue: "#c49cf0" },
];

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"];
const ROWS = 9; // hours shown
const ROW = 34; // px per hour

function CalendarIllustration() {
  return (
    <div
      aria-hidden
      className="rounded-2xl border border-line bg-surface p-4 shadow-2xl shadow-black/40"
    >
      <div className="mb-3 flex items-center justify-between px-1">
        <span className="text-sm font-semibold text-fg">October 12 – 16</span>
        <span className="rounded-full bg-raised px-2.5 py-1 text-[11px] text-muted">
          <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-accent align-middle" />
          Moved 1 block
        </span>
      </div>
      <div className="grid grid-cols-5 gap-1.5">
        {DAYS.map((d, i) => (
          <div key={d}>
            <div className="pb-2 text-center text-[11px] font-medium uppercase tracking-wider text-muted">
              {d}
            </div>
            <div
              className="relative rounded-md bg-ground/60"
              style={{
                height: ROWS * ROW,
                backgroundImage:
                  "repeating-linear-gradient(to bottom, transparent 0, transparent 33px, rgba(38,44,54,.8) 33px, rgba(38,44,54,.8) 34px)",
              }}
            >
              {BLOCKS.filter((b) => b.day === i).map((b) => (
                <div
                  key={`${b.day}-${b.start}`}
                  className="absolute inset-x-1 overflow-hidden rounded px-1.5 py-1 text-[10.5px] leading-tight"
                  style={{
                    top: b.start * ROW,
                    height: b.len * ROW - 3,
                    ...(b.busy
                      ? {
                          background:
                            "repeating-linear-gradient(135deg, #1a1f27 0 6px, #161a21 6px 12px)",
                          boxShadow: "inset 2px 0 0 #5a6272",
                          color: "#8c95a5",
                        }
                      : {
                          background: `color-mix(in srgb, ${b.hue} 24%, #151920)`,
                          boxShadow: `inset 2px 0 0 ${b.hue}`,
                          color: "#e8eaef",
                        }),
                  }}
                >
                  {b.label}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
