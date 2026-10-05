"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  Calendar,
  dateFnsLocalizer,
  type EventProps,
  type View,
} from "react-big-calendar";
import withDragAndDrop from "react-big-calendar/lib/addons/dragAndDrop";
import { format, getDay, parse, startOfWeek } from "date-fns";
import { enUS } from "date-fns/locale/en-US";

import "react-big-calendar/lib/css/react-big-calendar.css";
import "react-big-calendar/lib/addons/dragAndDrop/styles.css";
import "./calendar.css";

import {
  activityLabel,
  blockEnd,
  blockStart,
  occurrences,
  type Block,
  type Commitment,
} from "@/lib/api";

const localizer = dateFnsLocalizer({
  format,
  parse,
  startOfWeek: () => startOfWeek(new Date(), { locale: enUS }),
  getDay,
  locales: { "en-US": enUS },
});

type StudyEvent = {
  id: string;
  /** "study" blocks are the plan; "busy" ones are commitments it works around. */
  kind: "study" | "busy";
  title: string;
  /** The bare assignment name, for blocks too short to spend space on a verb. */
  short: string;
  course: string;
  color: string;
  start: Date;
  end: Date;
  pinned: boolean;
  /** A past block already reported on at a check-in. */
  completed?: boolean;
  /** A whole day off: shown as a full-height band, not a timed block. */
  off?: boolean;
};

const DnDCalendar = withDragAndDrop<StudyEvent>(Calendar);

/**
 * Pixel height of one hour. Not a constant: the calendar measures the space it
 * has and divides it by the hours on show, so the whole range fits without the
 * grid scrolling. Event cards read it to decide how much text they can show.
 */
const HourPx = createContext(60);

type Hover = { event: StudyEvent; rect: DOMRect } | null;
const SetHover = createContext<(h: Hover) => void>(() => {});

/** Below this the grid stops shrinking and scrolls instead of becoming unreadable. */
const MIN_HOUR_PX = 28;

const clock = (d: Date) => format(d, "h:mm");
const BUSY_COLOR = "#5a6272";
const KIND_LABEL: Record<string, string> = {
  class: "Class",
  work: "Work",
  other: "Busy",
  off: "Day off",
};

const hoursOf = (e: StudyEvent) =>
  (e.end.getTime() - e.start.getTime()) / 3_600_000;

/** 1.75 -> "1.75h", 2 -> "2h", 2.6667 -> "2.67h" */
const fmtHours = (h: number) => `${Number(h.toFixed(2))}h`;

function EventCard({ event }: EventProps<StudyEvent>) {
  const hourPx = useContext(HourPx);
  const setHover = useContext(SetHover);
  const hoverProps = {
    onMouseEnter: (e: React.MouseEvent<HTMLDivElement>) =>
      setHover({ event, rect: e.currentTarget.getBoundingClientRect() }),
    onMouseLeave: () => setHover(null),
    onMouseDown: () => setHover(null), // don't float over a block being dragged
  };
  const h = hoursOf(event);
  const px = h * hourPx;
  const range = `${clock(event.start)}–${clock(event.end)}`; // the gutter already says AM/PM
  const dur = fmtHours(h);
  // Layout by the block's actual pixel height, since hours are sized to fit the
  // screen: one line of title when tight, title + time when there's room for
  // both, and the full label with duration when there's plenty.
  const size = px < 30 ? "is-tiny" : px < 56 ? "is-compact" : "";

  if (event.off) {
    return (
      <div className="cad-event" {...hoverProps}>
        <div className="cad-event-title">{event.title}</div>
        <div className="cad-event-time">No study</div>
      </div>
    );
  }

  if (size === "is-tiny") {
    return (
      <div className="cad-event is-tiny" {...hoverProps}>
        <div className="cad-event-title">{event.short}</div>
        {event.pinned && (
          <span
            className="cad-pin"
            style={{ background: event.color }}
            aria-label="pinned"
          />
        )}
      </div>
    );
  }

  return (
    <div className={`cad-event ${size}`} {...hoverProps}>
      <div
        className="cad-event-title"
        // Height of the block, minus room for the time line(s) and padding, at 15px a line.
        style={{
          WebkitLineClamp: Math.max(
            1,
            Math.floor((px - (size ? 22 : 40)) / 15),
          ),
        }}
      >
        {size ? event.short : event.title}
      </div>
      <div className="cad-event-time">
        <span>{range}</span>
        {!size && <span> · {dur}</span>}
      </div>
      {event.pinned && (
        <span
          className="cad-pin"
          style={{ background: event.color }}
          aria-label="pinned"
        />
      )}
    </div>
  );
}

/** Month cells are small: one line, start time and the bare task name. */
function MonthEvent({ event }: EventProps<StudyEvent>) {
  const setHover = useContext(SetHover);
  const t = format(event.start, event.start.getMinutes() ? "h:mmaaaaa" : "haaaaa");
  return (
    <div
      className="cad-month-event"
      onMouseEnter={(e) => setHover({ event, rect: e.currentTarget.getBoundingClientRect() })}
      onMouseLeave={() => setHover(null)}
      onMouseDown={() => setHover(null)}
    >
      <span className="cad-month-time">{t}</span> {event.short}
    </div>
  );
}

export default function ScheduleCalendar({
  changed,
  blocks,
  commitments,
  courseOf,
  colorOf,
  onMove,
  onResize,
  busy,
}: {
  /** Ids of blocks the last update added or moved, highlighted briefly. */
  changed?: Set<string>;
  blocks: Block[];
  commitments: Commitment[];
  /** assignment_id -> course code, shown on hover */
  courseOf: Record<string, string>;
  /** assignment_id -> "#rrggbb" */
  colorOf: Record<string, string>;
  onMove: (id: string, start: Date) => void;
  onResize: (id: string, hours: number) => void;
  busy: boolean;
}) {
  const events = useMemo<StudyEvent[]>(
    () =>
      blocks.map((b) => ({
        id: b.id,
        kind: "study" as const,
        title: activityLabel(b.assignment_title),
        short: b.assignment_title ?? "Study",
        course: (b.assignment_id && courseOf[b.assignment_id]) || "—",
        color: (b.assignment_id && colorOf[b.assignment_id]) || "#8c95a5",
        start: blockStart(b),
        end: blockEnd(b),
        pinned: b.pinned,
        completed: b.completed,
      })),
    [blocks, courseOf, colorOf],
  );

  // Commitments are drawn as background events: behind the plan, full column
  // width, never draggable, and never competing with study blocks for space.
  // They repeat indefinitely, so expand them over the span anyone could
  // plausibly page to: a month back through the end of the plan, plus slack.
  const busyEvents = useMemo<StudyEvent[]>(() => {
    const from = new Date();
    from.setDate(from.getDate() - 35);
    const to = new Date();
    to.setDate(to.getDate() + 150);
    for (const e of events) if (e.end > to) to.setTime(e.end.getTime());
    return commitments.flatMap((c) =>
      occurrences(c, from, to).map((o, i) => ({
        id: `busy-${c.id}-${i}`,
        kind: "busy" as const,
        title: c.title,
        short: c.title,
        course: [KIND_LABEL[c.kind] ?? "Busy", c.course_code]
          .filter(Boolean)
          .join(" · "),
        color: BUSY_COLOR,
        start: o.start,
        end: o.end,
        pinned: false,
        off: c.kind === "off",
      })),
    );
  }, [commitments, events]);

  // Open on the current week if anything is planned from today on, otherwise
  // on the first block.
  const defaultDate = useMemo(() => {
    const now = new Date();
    if (!events.length || events.some((e) => e.end >= now)) return now;
    return events[0].start;
  }, [events]);

  // Controlled navigation. Left uncontrolled, the calendar snapped back to its
  // default week on every re-render, so Next/Back/Today did nothing.
  const [date, setDate] = useState<Date | null>(null);
  const [view, setView] = useState<View>("week");
  const offDays = useMemo(
    () => new Set(busyEvents.filter((e) => e.off).map((e) => format(e.start, "yyyy-MM-dd"))),
    [busyEvents],
  );

  // Always show a full working day, 8am to 11pm, stretched to include any block
  // that falls outside it. The hours are then sized to fit the screen, so the
  // whole day is visible without scrolling.
  const [startHour, endHour] = useMemo(() => {
    let lo = 8;
    let hi = 23;
    // A day off spans midnight to midnight; letting it set the range would show
    // the whole night. It just fills whatever hours are on screen.
    for (const e of [...events, ...busyEvents.filter((b) => !b.off)]) {
      lo = Math.min(lo, e.start.getHours());
      const endsAt = e.end.getHours() + (e.end.getMinutes() > 0 ? 1 : 0);
      hi = Math.max(hi, e.end.getDate() !== e.start.getDate() ? 24 : endsAt);
    }
    return [lo, hi];
  }, [events, busyEvents]);

  // Measure the time grid and size each hour so the range fits exactly.
  const wrapRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<Hover>(null);
  // New blocks invalidate the hover card (its block may be gone). Adjusting
  // state during render, not in an effect, avoids a stale frame.
  const [hoverBlocks, setHoverBlocks] = useState(blocks);
  if (hoverBlocks !== blocks) {
    setHoverBlocks(blocks);
    setHover(null);
  }
  const [hourPx, setHourPx] = useState(60);
  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const hours = endHour - startHour;
    // Watch the time grid itself, not just the wrapper: the library lays the grid
    // out after mount, and a measurement taken before that is too small.
    const ro = new ResizeObserver(() => {
      const grid = wrap.querySelector<HTMLElement>(".rbc-time-content");
      if (!grid || grid.clientHeight === 0) return;
      const px = Math.floor((grid.clientHeight - 2) / hours);
      setHourPx(Math.max(MIN_HOUR_PX, px));
    });
    ro.observe(wrap);
    const watchGrid = () => {
      const grid = wrap.querySelector<HTMLElement>(".rbc-time-content");
      if (grid) ro.observe(grid);
    };
    watchGrid();
    // The grid element is replaced when the view changes (week/day); pick up the new one.
    const mo = new MutationObserver(watchGrid);
    mo.observe(wrap, { childList: true, subtree: true });
    return () => {
      ro.disconnect();
      mo.disconnect();
    };
  }, [startHour, endHour, events.length]);

  if (!events.length && !busyEvents.length) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center rounded-xl border border-dashed border-line text-sm text-muted">
        No study blocks yet. Upload a syllabus to build a schedule.
      </div>
    );
  }

  return (
    <HourPx.Provider value={hourPx}>
      <SetHover.Provider value={setHover}>
        <div
          className={`cad-cal flex min-h-0 flex-1 flex-col ${busy ? "pointer-events-none opacity-60" : ""}`}
          style={{ "--hour-px": `${hourPx}px` } as React.CSSProperties}
          data-fits={hourPx > MIN_HOUR_PX ? "" : undefined}
        >
          <div ref={wrapRef} className="min-h-0 flex-1">
            <DnDCalendar
              localizer={localizer}
              events={events}
              backgroundEvents={busyEvents}
              view={view}
              onView={setView}
              views={["month", "week", "day", "agenda"]}
              date={date ?? defaultDate}
              onNavigate={(d) => setDate(d)}
              step={15}
              timeslots={4}
              min={new Date(1970, 0, 1, startHour, 0)}
              max={new Date(1970, 0, 1, endHour - 1, 59)}
              style={{ height: "100%" }}
              // Blocks never overlap (the scheduler lays each day out sequentially), so
              // every event gets the full column width instead of being split.
              dayLayoutAlgorithm="no-overlap"
              components={{ event: EventCard, month: { event: MonthEvent } }}
              // Month cells have no time axis: show days off as a shaded day.
              dayPropGetter={(d) =>
                view === "month" && offDays.has(format(d, "yyyy-MM-dd"))
                  ? { className: "cad-dayoff" }
                  : {}
              }
              resizableAccessor={() => view !== "month"}
              popup
              resizable
              // Dragging or resizing pins the block: the next reschedule leaves it
              // alone and charges its hours to the assignment instead of replanning.
              onEventDrop={({ event, start }) => {
                // Dropping on a month cell moves the day, not the time of day.
                const to = new Date(start as Date);
                if (view === "month") {
                  to.setHours(event.start.getHours(), event.start.getMinutes(), 0, 0);
                }
                onMove(event.id, to);
              }}
              onEventResize={({ event, start, end }) =>
                onResize(
                  event.id,
                  ((end as Date).getTime() - (start as Date).getTime()) /
                    3_600_000,
                )
              }
              eventPropGetter={(event) => {
                if (event.kind === "busy") {
                  return {
                    className: "cad-busy",
                    style: {
                      background:
                        "repeating-linear-gradient(135deg, #1a1f27 0 6px, #161a21 6px 12px)",
                      boxShadow: `inset 3px 0 0 ${BUSY_COLOR}`,
                      color: "#8c95a5",
                    },
                  };
                }
                const hue = event.color;
                return {
                  className:
                    [changed?.has(event.id) && "cad-changed", event.completed && "cad-done"]
                      .filter(Boolean)
                      .join(" ") || undefined,
                  style: {
                    background: `color-mix(in srgb, ${hue} ${event.pinned ? 34 : 22}%, #151920)`,
                    boxShadow: `inset 3px 0 0 ${hue}`,
                    color: "#e8eaef",
                  },
                };
              }}
              tooltipAccessor={null}
            />
          </div>
          <p className="mt-2 shrink-0 text-xs text-muted">
            Drag or resize a block to pin it. Pinned blocks{" "}
            <span className="inline-block h-1.5 w-1.5 translate-y-[-1px] rounded-full bg-muted align-middle" />{" "}
            keep their place when the schedule is rebuilt. Striped blocks are
            commitments; study is planned around them.
          </p>
        </div>
        {hover && <HoverCard hover={hover} />}
      </SetHover.Provider>
    </HourPx.Provider>
  );
}

/**
 * Full details for a block, shown on hover. Fixed-positioned so it escapes the
 * block's clipping, placed beside the block (right if there's room, else left)
 * and kept on screen vertically.
 */
function HoverCard({ hover }: { hover: NonNullable<Hover> }) {
  const { event, rect } = hover;
  const W = 240;
  const room = typeof window !== "undefined" ? window.innerWidth : 1440;
  const left =
    rect.right + 8 + W < room ? rect.right + 8 : Math.max(8, rect.left - 8 - W);
  const top = Math.min(
    Math.max(8, rect.top),
    (typeof window !== "undefined" ? window.innerHeight : 800) - 120,
  );
  const h = hoursOf(event);
  return (
    <div
      role="tooltip"
      className="pointer-events-none fixed z-50 rounded-lg border border-line bg-raised px-3 py-2.5 shadow-xl shadow-black/40"
      style={{
        left,
        top,
        width: W,
        borderLeft: `3px solid ${event.color}`,
      }}
    >
      <p className="text-[13px] font-semibold leading-snug text-fg">
        {event.title}
      </p>
      <p className="mt-1 font-mono text-[11px] text-muted">
        {format(event.start, "EEE MMM d")}
        {!event.off && (
          <>
            {" "}
            · {format(event.start, "h:mm")}–{format(event.end, "h:mm a")}
          </>
        )}
      </p>
      <p className="mt-0.5 font-mono text-[11px] text-muted">
        {event.off ? "All day" : fmtHours(h)} · {event.course}
      </p>
      {event.pinned && (
        <p className="mt-1.5 text-[11px] text-accent">
          Pinned — stays put when you rebuild
        </p>
      )}
      {event.kind === "busy" && (
        <p className="mt-1.5 text-[11px] text-muted">
          Commitment — no study is planned here
        </p>
      )}
    </div>
  );
}
