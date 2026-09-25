/**
 * Typed client for the Cadence API.
 *
 * These types mirror app/schemas.py. Keeping them in one place means a backend
 * shape change breaks the build here rather than failing silently at runtime.
 */

// Same-origin by default: next.config.ts proxies /api/* to FastAPI. Set
// NEXT_PUBLIC_API_BASE only to bypass the proxy and call the API directly.
const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

// Auth is deferred; every request acts as this user. When Clerk lands this
// becomes the Clerk user id and nothing else changes.
const EXTERNAL_ID = "demo";

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
  url.searchParams.set("external_id", EXTERNAL_ID);
  const res = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
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

export const reschedule = () =>
  request<RescheduleSummary>("/reschedule", { method: "POST" });

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
  form.append("external_id", EXTERNAL_ID);
  if (termStart) form.append("term_start", termStart);

  const res = await fetch(`${BASE}/api/syllabus/stream`, {
    method: "POST",
    body: form,
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
