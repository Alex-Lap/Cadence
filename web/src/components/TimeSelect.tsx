"use client";

import { useState } from "react";

const STEPS = ["00", "15", "30", "45"];
const HOURS = Array.from({ length: 12 }, (_, i) => String(i + 1));

const selectCls =
  "rounded border border-line bg-raised px-1.5 py-1 text-xs text-fg focus:border-accent/60 focus:outline-none";

/**
 * A time as hour / minute / AM-PM dropdowns. Minutes come in 15-minute steps,
 * which covers almost every schedule; "Other" swaps in a free minute box for
 * the class that runs 9:35-10:50.
 *
 * Value is "HH:MM" (24h) or "" for unset. With `allowEmpty` the hour list
 * starts with a blank entry, so the field can be cleared back to the default.
 */
export default function TimeSelect({
  value,
  onChange,
  allowEmpty = false,
  label,
}: {
  value: string;
  onChange: (v: string) => void;
  allowEmpty?: boolean;
  label: string;
}) {
  const [h24, min] = value ? value.split(":").map(Number) : [NaN, NaN];
  const set = !Number.isNaN(h24);
  const hour12 = set ? String(((h24 + 11) % 12) + 1) : "";
  const pm = set ? h24 >= 12 : true;
  const mm = set ? String(min).padStart(2, "0") : "00";

  // Show the free-entry box when the user asked for it or the stored minute is off-grid.
  const [custom, setCustom] = useState(set && !STEPS.includes(mm));
  const showCustom = custom || (set && !STEPS.includes(mm));

  function emit(h: string, m: string, isPm: boolean) {
    if (!h) return onChange("");
    const n = (Number(h) % 12) + (isPm ? 12 : 0);
    const mins = Math.min(59, Math.max(0, Number(m) || 0));
    onChange(`${String(n).padStart(2, "0")}:${String(mins).padStart(2, "0")}`);
  }

  return (
    <div className="flex items-center gap-1" role="group" aria-label={label}>
      <select
        aria-label={`${label} hour`}
        value={hour12}
        onChange={(e) => {
          const h = e.target.value;
          // First pick: guess AM/PM from the hour (7-11 reads as morning,
          // 12-6 as afternoon or evening). Afterwards keep what the user chose.
          const guessPm = set ? pm : !(Number(h) >= 7 && Number(h) <= 11);
          emit(h, mm, guessPm);
        }}
        className={selectCls}
      >
        {(allowEmpty || !set) && <option value="">--</option>}
        {HOURS.map((h) => (
          <option key={h} value={h}>
            {h}
          </option>
        ))}
      </select>
      <span className="text-muted">:</span>
      {showCustom ? (
        <input
          aria-label={`${label} minute`}
          type="number"
          min={0}
          max={59}
          value={set ? min : ""}
          placeholder="mm"
          onChange={(e) => emit(hour12 || "12", e.target.value, pm)}
          onBlur={() => {
            // Back to the dropdown once the minute lands on the grid again.
            if (STEPS.includes(mm)) setCustom(false);
          }}
          className={`${selectCls} w-12`}
        />
      ) : (
        <select
          aria-label={`${label} minute`}
          value={mm}
          disabled={!set}
          onChange={(e) =>
            e.target.value === "other"
              ? setCustom(true)
              : emit(hour12, e.target.value, pm)
          }
          className={`${selectCls} disabled:opacity-50`}
        >
          {STEPS.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
          <option value="other">Other…</option>
        </select>
      )}
      <select
        aria-label={`${label} AM or PM`}
        value={pm ? "pm" : "am"}
        disabled={!set}
        onChange={(e) => emit(hour12, mm, e.target.value === "pm")}
        className={`${selectCls} disabled:opacity-50`}
      >
        <option value="am">AM</option>
        <option value="pm">PM</option>
      </select>
    </div>
  );
}
