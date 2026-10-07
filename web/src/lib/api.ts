/**
 * Typed client for the Cadence API.
 *
 * These types mirror app/schemas.py. Keeping them in one place means a backend
 * shape change breaks the build here rather than failing silently at runtime.
 */

// Same-origin by default: next.config.ts proxies /api/* to FastAPI. Set
// NEXT_PUBLIC_API_BASE only to bypass the proxy and call the API directly.
const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

// Who the API acts for comes from the Clerk session, never from the request:
// a short-lived token on every fetch, set once by the signed-in app shell.
type TokenSource = () => Promise<string | null>;
let tokenSource: TokenSource | null = null;

export function setTokenSource(fn: TokenSource) {
  tokenSource = fn;
}

async function authHeaders(): Promise<Record<string, string>> {
  const token = tokenSource ? await tokenSource() : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * Upcoming study blocks as an .ics file for Google/Apple/Outlook. A plain
 * link: the browser sends Clerk's session cookie with it, which the API accepts.
 */
export const calendarExportUrl = () => `${BASE}/api/calendar.ics`;

export type Assignment = {
  id: string;
  course_code: string;
  title: string;
  due_at: string | null;
  available_at: string | null;
  weight: number | null;
  estimated_hours: number;
  needs_date: boolean;
  is_category: boolean;
  /** Attendance, participation: graded, but nothing to date or schedule. */
  is_participation: boolean;
  color: string | null;
};

export type Block = {
  id: string;
  assignment_id: string | null;
  assignment_title: string | null;
  day: string;        // YYYY-MM-DD
  start_time: string; // HH:MM:SS
  hours: number;
  pinned: boolean;
  /** Reviewed at a check-in. */
  completed: boolean;
};

export type Course = {
  id: string;
  code: string;
  title: string;
  term: string | null;
  assignments: number;
};

export type RescheduleSummary = {
  scheduled: number;
  blocks: number;
  pinned_kept: number;
  unscheduled: string[];
  needs_date: string[];
  categories: string[];
  /** How much of the previous plan survived the rebuild. */
  churn?: { kept: number; moved: number; added: number };
};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function detailOf(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (body.detail) return JSON.stringify(body.detail);
  } catch {
    /* non-JSON error body */
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = new URL(`${BASE}/api${path}`, window.location.origin);
  const res = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(await authHeaders()),
      ...init?.headers,
    },
  });
  if (!res.ok) throw new ApiError(res.status, await detailOf(res, res.statusText));
  return res.json() as Promise<T>;
}

export const getSchedule = () =>
  request<{ blocks: Block[]; unscheduled: string[] }>("/schedule");

export const getAssignments = () => request<Assignment[]>("/assignments");

export const getCourses = () => request<Course[]>("/courses");

export const deleteCourse = (id: string) =>
  request<RescheduleSummary>(`/courses/${id}`, { method: "DELETE" });

/** Rebuild the plan. By default still-valid blocks stay put; `fresh` starts over. */
export const reschedule = (fresh = false) =>
  request<RescheduleSummary>(`/reschedule${fresh ? "?fresh=true" : ""}`, {
    method: "POST",
  });

export const patchAssignment = (
  id: string,
  patch: {
    due_at?: string | null;
    available_at?: string | null;
    estimated_hours?: number;
    is_category?: boolean;
    color?: string | null;
  },
) =>
  request<Assignment>(`/assignments/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });

export const patchBlock = (
  id: string,
  patch: { day?: string; start_time?: string; hours?: number },
) =>
  request<Block>(`/blocks/${id}`, { method: "PATCH", body: JSON.stringify(patch) });

/* ------------------------------------------------------- commitments */

/** "off" is a whole day (or several) with no study at all. */
export type CommitmentKind = "class" | "work" | "other" | "off";

export type Commitment = {
  id: string;
  /** False for meetings read from a syllabus until the user checks them. */
  confirmed: boolean;
  /** Why an unconfirmed meeting's times look wrong, if they do. */
  warning: string | null;
  /** The syllabus line it was read from. */
  note: string | null;
  title: string;
  kind: CommitmentKind;
  source: string;
  weekday: number | null; // 0 = Monday, matching Python
  on_date: string | null; // YYYY-MM-DD
  starts_on: string | null;
  ends_on: string | null;
  start_time: string; // HH:MM:SS
  end_time: string;
  course_id: string | null;
  course_code: string | null;
};

export type NewCommitment = {
  title: string;
  kind: CommitmentKind;
  weekday?: number;
  on_date?: string;
  /** Last day of a multi-day one-off, e.g. a break. */
  ends_on?: string;
  start_time: string;
  end_time: string;
  course_id?: string;
};

export type StudySettings = {
  study_start: string | null;
  study_end: string | null;
  max_hours_per_day: number | null;
};

export type SettingsOut = StudySettings & {
  /** What the scheduler uses when a field above is null. */
  effective: StudySettings;
};

export const getCommitments = () => request<Commitment[]>("/commitments");

export const createCommitment = (body: NewCommitment) =>
  request<Commitment>("/commitments", { method: "POST", body: JSON.stringify(body) });

export const deleteCommitment = (id: string) =>
  request<RescheduleSummary>(`/commitments/${id}`, { method: "DELETE" });

export const patchCommitment = (
  id: string,
  patch: { title?: string; start_time?: string; end_time?: string; confirmed?: boolean },
) =>
  request<Commitment>(`/commitments/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });

export const getSettings = () => request<SettingsOut>("/settings");

export const putSettings = (body: StudySettings) =>
  request<SettingsOut>("/settings", { method: "PUT", body: JSON.stringify(body) });

/** Python counts weekdays from Monday; JavaScript's getDay() from Sunday. */
export const pyWeekday = (d: Date) => (d.getDay() + 6) % 7;

/** Every concrete occurrence of a commitment between two dates, inclusive. */
export function occurrences(
  c: Commitment,
  from: Date,
  to: Date,
): { start: Date; end: Date }[] {
  const at = (day: string) => ({
    start: new Date(`${day}T${c.start_time}`),
    end: new Date(`${day}T${c.end_time}`),
  });
  if (c.on_date) {
    // One day, or every day from on_date through ends_on.
    const out: { start: Date; end: Date }[] = [];
    const last = new Date(`${c.ends_on ?? c.on_date}T00:00:00`);
    for (const d = new Date(`${c.on_date}T00:00:00`); d <= last; d.setDate(d.getDate() + 1)) {
      if (d >= from && d <= to) out.push(at(toDateStr(d)));
    }
    return out;
  }
  const out: { start: Date; end: Date }[] = [];
  const cursor = new Date(from);
  cursor.setHours(0, 0, 0, 0);
  for (; cursor <= to; cursor.setDate(cursor.getDate() + 1)) {
    if (pyWeekday(cursor) !== c.weekday) continue;
    const day = toDateStr(cursor);
    if (c.starts_on && day < c.starts_on) continue;
    if (c.ends_on && day > c.ends_on) continue;
    out.push(at(day));
  }
  return out;
}

/* ------------------------------------------------------------- check-in */

export type CheckInTask = {
  assignment_id: string;
  title: string;
  course_code: string;
  due_at: string | null;
  estimated_hours: number;
  completed_hours: number;
  planned_hours: number;
};

export type CheckInEntry = {
  assignment_id: string;
  hours_spent: number;
  done?: boolean;
  hours_left?: number;
};

export type CheckInResult = RescheduleSummary & {
  reviewed_blocks: number;
  adjustments: { course_code: string; before: number; after: number; rescaled: number }[];
};

export const getCheckIn = () =>
  request<{ since: string | null; tasks: CheckInTask[] }>("/checkin");

export const postCheckIn = (entries: CheckInEntry[]) =>
  request<CheckInResult>("/checkin", { method: "POST", body: JSON.stringify({ entries }) });

/* ------------------------------------------------------------------ upload */

export type StreamEvent =
  | { event: "start"; data: { user_id: string } }
  | { event: "node"; data: { node: string; trace: string[] } }
  | { event: "persisted"; data: { courses: string[] } }
  | { event: "scheduled"; data: RescheduleSummary }
  | { event: "done"; data: { user_id: string } }
  | { event: "error"; data: { detail: string } };

/**
 * Upload a syllabus and consume server-sent events as they arrive.
 *
 * EventSource can't be used: the endpoint is a POST carrying a file. So this
 * reads response.body directly and splits SSE frames off a buffer.
 *
 * Two distinct failure modes matter here. A validation failure happens before
 * the stream opens and rejects this promise. A failure *during* the run arrives
 * as an `error` event on a response HTTP considers successful -- so callers must
 * handle that event, not just catch.
 */
export async function uploadSyllabusStream(
  file: File,
  termStart: string | null,
  onEvent: (e: StreamEvent) => void,
): Promise<void> {
  const form = new FormData();
  form.append("file", file);
  if (termStart) form.append("term_start", termStart);

  const res = await fetch(`${BASE}/api/syllabus/stream`, {
    method: "POST",
    body: form,
    headers: await authHeaders(),
  });
  if (!res.ok) throw new ApiError(res.status, await detailOf(res, res.statusText));
  if (!res.body) throw new Error("No response body to stream.");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // A frame ends at a blank line; whatever follows the last one is partial.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      let name = "";
      let payload = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) name = line.slice(7);
        else if (line.startsWith("data: ")) payload = line.slice(6);
      }
      if (name) {
        onEvent({
          event: name,
          data: payload ? JSON.parse(payload) : {},
        } as StreamEvent);
      }
    }
  }
}

/* ------------------------------------------------------------- date helpers */

const pad = (n: number) => String(n).padStart(2, "0");

export const toDateStr = (d: Date) =>
  `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

export const toTimeStr = (d: Date) => `${pad(d.getHours())}:${pad(d.getMinutes())}:00`;

/** Blocks arrive as a local date plus a wall-clock time; build a local Date. */
export const blockStart = (b: Block) => new Date(`${b.day}T${b.start_time}`);

export const blockEnd = (b: Block) =>
  new Date(blockStart(b).getTime() + b.hours * 3600 * 1000);

/**
 * What a study block is FOR, as a label. A block titled "Final Exam" reads as
 * the exam itself; the block is time spent preparing for it.
 */
export function activityLabel(title: string | null): string {
  if (!title) return "Study";
  if (/\b(exam|midterm|final|quiz|test)\b/i.test(title)) return `Study for ${title}`;
  if (/\b(presentation|talk|demo)\b/i.test(title)) return `Prepare ${title}`;
  if (/\b(reading|chapter)\b/i.test(title)) return `Read ${title}`;
  return `Work on ${title}`;
}
