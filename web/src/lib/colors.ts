import type { Assignment } from "./api";

/**
 * Task colours. Picked to read as a tinted fill on the dark ground and to stay
 * distinguishable from their neighbours. Also the preset swatches in the picker.
 */
export const TASK_COLORS = [
  "#6ea8fe", // blue
  "#5fc7a6", // teal
  "#e9a25b", // orange
  "#c595ea", // violet
  "#ef8b8b", // rose
  "#a3cf6a", // lime
  "#f2d06b", // yellow
  "#6fd3e8", // cyan
];

/**
 * assignment id -> colour. A colour the user chose wins; everything else is
 * assigned from the palette in due-date order, so tasks that sit next to each
 * other on the calendar get different colours.
 */
export function taskColors(assignments: Assignment[]): Record<string, string> {
  const ordered = assignments
    .filter((a) => !a.is_category)
    .sort(
      (a, b) =>
        (a.due_at ?? "9999").localeCompare(b.due_at ?? "9999") ||
        a.title.localeCompare(b.title),
    );
  const out: Record<string, string> = {};
  ordered.forEach((a, i) => {
    out[a.id] = a.color ?? TASK_COLORS[i % TASK_COLORS.length];
  });
  return out;
}
