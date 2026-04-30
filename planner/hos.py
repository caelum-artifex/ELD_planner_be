"""
FMCSA HOS Engine – Property-carrying CMV, 70 h / 8-day rule.

Regulations implemented (49 CFR Part 395):
  §395.3(a)(1)       – 10 consecutive off-duty/sleeper hours before driving
  §395.3(a)(2)       – 14-hour driving window (wall-clock from duty start)
  §395.3(a)(3)       – 11-hour driving limit
  §395.3(a)(3)(ii)   – 30-minute break required after 8 CUMULATIVE driving hours
  §395.3(b)          – 70-hour / 8-day on-duty cycle (rolling window)
  §395.3(c)          – 34-hour off-duty restart resets the 70h cycle

Key design guarantee:
  driving_capacity() caps every drive chunk so no limit is ever exceeded.
  Mandatory rests are inserted BEFORE the next driving chunk starts, not after.
  This matches real ELD/HOS system behaviour described in §395.3(a)(3)(ii):
  "Driving is not permitted if MORE THAN 8 hours have passed since the end of
  the driver's last break …"  → driver must break AT or BEFORE 8 h, never after.

Assumptions (per assessment spec):
  • Property-carrying, single driver
  • 70 h / 8-day cycle
  • No adverse driving conditions exception
  • Fuel stop every ≤ 1,000 miles (0.5 h on-duty)
  • 1 h on-duty for pickup, 1 h on-duty for dropoff
  • Average driving speed: 55 mph
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

# ── FMCSA limits ──────────────────────────────────────────────────────────────
DRIVING_LIMIT: float = 11.0   # §395.3(a)(3)   – max driving per duty period
DUTY_WINDOW: float = 14.0     # §395.3(a)(2)   – 14-hour window (wall-clock)
BREAK_AFTER: float = 8.0      # §395.3(a)(3)(ii) – break required after 8 h cumul. driving
BREAK_MIN: float = 0.5        # 30-minute minimum break
DAILY_RESET: float = 10.0     # §395.3(a)(1)   – consecutive off-duty to reset clocks
CYCLE_LIMIT: float = 70.0     # §395.3(b)      – 70 h in any 8 consecutive days
CYCLE_RESTART: float = 34.0   # §395.3(c)      – 34 h restart resets full cycle
CYCLE_DAYS: int = 8

AVG_SPEED_MPH: float = 55.0
FUEL_INTERVAL_MILES: float = 1_000.0
FUEL_STOP_HOURS: float = 0.5

# ── Activity → frontend status mapping ────────────────────────────────────────
_STATUS: dict[str, str] = {
    "driving": "driving",
    "sleeper": "sleeper",
    "off_duty": "off_duty",
    "on_duty": "on_duty_not_driving",
}


# ── State object ──────────────────────────────────────────────────────────────
@dataclass
class HosState:
    """
    Tracks all driver limits simultaneously.

    hours_driven      → cumul. driving since last daily reset  (11h rule)
    hours_since_break → cumul. driving since last ≥30-min break (8h rule)
    window_elapsed    → wall-clock hours since duty window opened (14h rule)
    cycle             → on-duty hours per day, oldest at index 0  (70h/8d rule)
    """

    hours_driven: float = 0.0
    hours_since_break: float = 0.0
    window_elapsed: float = 0.0
    cycle: list[float] = field(default_factory=lambda: [0.0] * CYCLE_DAYS)

    # ── derived ───────────────────────────────────────────────────────────────
    @property
    def cycle_used(self) -> float:
        return sum(self.cycle)

    # ── capacity ─────────────────────────────────────────────────────────────
    def driving_capacity(self) -> float:
        """
        Maximum hours the driver may drive RIGHT NOW before hitting any limit.
        Returning 0 means at least one mandatory rest must be inserted first.
        """
        return max(
            0.0,
            min(
                DRIVING_LIMIT - self.hours_driven,       # 11h daily cap
                DUTY_WINDOW - self.window_elapsed,        # 14h window cap
                BREAK_AFTER - self.hours_since_break,     # 8h break cap  ← KEY
                CYCLE_LIMIT - self.cycle_used,            # 70h cycle cap
            ),
        )

    # ── flags ─────────────────────────────────────────────────────────────────
    def needs_break(self) -> bool:
        """30-min break due – driver has hit 8 cumulative driving hours."""
        return self.hours_since_break >= BREAK_AFTER

    def needs_daily_reset(self) -> bool:
        """10-hour rest due – 11h driving used or 14h window expired."""
        return (
            self.hours_driven >= DRIVING_LIMIT
            or self.window_elapsed >= DUTY_WINDOW
        )

    def needs_cycle_restart(self) -> bool:
        """34-hour restart due – 70h cycle exhausted."""
        return self.cycle_used >= CYCLE_LIMIT

    # ── mutators ──────────────────────────────────────────────────────────────
    def add_driving(self, h: float) -> None:
        self.hours_driven += h
        self.hours_since_break += h
        self.window_elapsed += h   # 14h window is wall-clock; driving counts
        self.cycle[-1] += h        # on-duty → counts toward 70h cycle

    def add_on_duty(self, h: float) -> None:
        """On-duty not driving (stops, fuel, inspection, paperwork, etc.)."""
        self.window_elapsed += h
        self.cycle[-1] += h
        # Any consecutive non-driving period ≥ 30 min satisfies the break rule.
        if h >= BREAK_MIN:
            self.hours_since_break = 0.0

    def add_rest(self, h: float) -> None:
        """
        Off-duty or sleeper rest that does NOT reset the daily clocks (< 10 h).
        The 14h window keeps ticking even during short breaks.
        A ≥30-min off-duty period resets the 8-hour break counter.
        """
        self.window_elapsed += h   # 14h window is consecutive; clock keeps going
        if h >= BREAK_MIN:
            self.hours_since_break = 0.0

    def daily_reset(self) -> None:
        """
        After ≥10 consecutive off-duty/sleeper hours.
        Resets 11h driving and 14h window clocks.
        Advances the rolling 8-day window by one day.
        """
        self.hours_driven = 0.0
        self.hours_since_break = 0.0
        self.window_elapsed = 0.0
        # Advance rolling window: oldest day drops off, fresh day appended.
        self.cycle = self.cycle[1:] + [0.0]

    def cycle_reset(self) -> None:
        """
        After ≥34 consecutive off-duty hours.
        Full 70h/8-day cycle resets to zero (§395.3(c)).
        """
        self.cycle = [0.0] * CYCLE_DAYS
        # Also resets daily clocks because 34h ≥ 10h.
        self.hours_driven = 0.0
        self.hours_since_break = 0.0
        self.window_elapsed = 0.0


# ── Low-level helpers ─────────────────────────────────────────────────────────
def _seg(
    segments: list[dict[str, Any]],
    start: datetime,
    end: datetime,
    activity: str,
    location: str,
    notes: str,
) -> None:
    if end <= start:
        return
    segments.append(
        {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "activity_type": activity,
            "status": _STATUS.get(activity, "on_duty_not_driving"),
            "location": location,
            "notes": notes,
            "hours": round((end - start).total_seconds() / 3600, 2),
        }
    )


def _mandatory_rest(
    state: HosState,
    now: datetime,
    segments: list[dict[str, Any]],
    location: str,
) -> datetime:
    """
    Insert the single minimum-required rest period and update state.

    Priority order (most-disruptive last so we always use shortest valid rest):
      1. 30-min break  (only satisfies break rule)
      2. 10-hour reset (satisfies 11h/14h and also the break rule)
      3. 34-hour restart (satisfies cycle limit and both of the above)

    Called in a WHILE loop until driving_capacity() > 0, so multiple rests
    are chained automatically when more than one limit is hit at once.
    """
    # 34h restart trumps everything when cycle is exhausted.
    if state.needs_cycle_restart():
        end = now + timedelta(hours=CYCLE_RESTART)
        _seg(
            segments, now, end, "off_duty", location,
            "34-hour restart – resets 70 h/8-day cycle (§395.3(c))",
        )
        state.cycle_reset()
        return end

    # 10h reset when 11h driving used OR 14h window expired.
    if state.needs_daily_reset():
        end = now + timedelta(hours=DAILY_RESET)
        _seg(
            segments, now, end, "sleeper", location,
            "10-hour rest – resets 11 h driving & 14 h window (§395.3(a)(1))",
        )
        state.daily_reset()
        return end

    # 30-min break when 8 cumulative driving hours reached.
    # This is inserted BEFORE the next chunk, guaranteeing no driving exceeds 8 h.
    if state.needs_break():
        end = now + timedelta(hours=BREAK_MIN)
        _seg(
            segments, now, end, "off_duty", location,
            "30-minute break (§395.3(a)(3)(ii)) – 8 h cumul. driving reached",
        )
        state.add_rest(BREAK_MIN)
        return end

    # Should never reach here if called correctly (only when capacity == 0).
    return now


# ── Core drive function ───────────────────────────────────────────────────────
def _drive(
    miles: float,
    now: datetime,
    state: HosState,
    segments: list[dict[str, Any]],
    location: str,
    label: str,
    miles_since_fuel: float = 0.0,
) -> tuple[datetime, float]:
    """
    Simulate driving `miles` from `location`.

    For each driving chunk:
      1. Resolve ALL mandatory rests BEFORE touching the wheel.
         This guarantees the driver is always HOS-compliant when they start.
      2. Compute the largest chunk allowed by driving_capacity().
         Because driving_capacity() is the min of all four limits, the chunk
         will never exceed any single constraint.
      3. Insert fuel stop when the 1,000-mile cadence is reached.
    """
    remaining = miles

    while remaining > 0:
        # ── Step 1: clear any active limits BEFORE driving ─────────────────
        # driving_capacity() == 0 means at least one limit needs resolution.
        while state.driving_capacity() <= 0:
            now = _mandatory_rest(state, now, segments, location)

        # ── Step 2: drive the maximum allowed chunk ────────────────────────
        cap_h = state.driving_capacity()
        chunk_mi = min(remaining, cap_h * AVG_SPEED_MPH)
        chunk_h = chunk_mi / AVG_SPEED_MPH

        end = now + timedelta(hours=chunk_h)
        _seg(segments, now, end, "driving", location, label)
        state.add_driving(chunk_h)
        remaining -= chunk_mi
        miles_since_fuel += chunk_mi
        now = end

        # ── Step 3: fuel stop every ≤1,000 miles ──────────────────────────
        if miles_since_fuel >= FUEL_INTERVAL_MILES:
            fuel_end = now + timedelta(hours=FUEL_STOP_HOURS)
            _seg(
                segments, now, fuel_end, "on_duty", location,
                "Fuel stop (≤1,000-mile cadence per assessment spec)",
            )
            state.add_on_duty(FUEL_STOP_HOURS)
            miles_since_fuel = 0.0
            now = fuel_end

    return now, miles_since_fuel


# ── On-duty stop (pickup / dropoff) ──────────────────────────────────────────
def _on_duty_stop(
    now: datetime,
    state: HosState,
    segments: list[dict[str, Any]],
    location: str,
    label: str,
    hours: float = 1.0,
) -> datetime:
    """
    Insert an on-duty not-driving stop.
    Only clears the cycle limit (on-duty work is legal after the 14h window).
    """
    while state.needs_cycle_restart():
        now = _mandatory_rest(state, now, segments, location)

    end = now + timedelta(hours=hours)
    _seg(segments, now, end, "on_duty", location, label)
    state.add_on_duty(hours)
    return end


# ── Daily log sheet builder ───────────────────────────────────────────────────
def _daily_logs(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Splits the flat segment list into per-calendar-day buckets,
    producing one ELD log sheet entry per day.
    """
    by_day: dict[str, list[dict[str, Any]]] = {}

    for segment in segments:
        start = datetime.fromisoformat(segment["start"])
        end = datetime.fromisoformat(segment["end"])
        pointer = start

        while pointer < end:
            day_start = pointer.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            part_end = min(end, day_end)
            date_key = day_start.date().isoformat()

            by_day.setdefault(date_key, []).append(
                {
                    "start_hour": (pointer - day_start).total_seconds() / 3600,
                    "end_hour": (part_end - day_start).total_seconds() / 3600,
                    "status": segment["status"],
                    "notes": segment["notes"],
                }
            )
            pointer = part_end

    output: list[dict[str, Any]] = []
    for date_key in sorted(by_day.keys()):
        entries = by_day[date_key]
        totals: dict[str, float] = {
            "driving_hours": 0.0,
            "on_duty_not_driving_hours": 0.0,   # stops, fuel, breaks – NOT driving
            "off_duty_hours": 0.0,
            "sleeper_hours": 0.0,
        }
        for e in entries:
            dur = e["end_hour"] - e["start_hour"]
            if e["status"] == "driving":
                totals["driving_hours"] += dur
            elif e["status"] == "on_duty_not_driving":
                totals["on_duty_not_driving_hours"] += dur
            elif e["status"] == "off_duty":
                totals["off_duty_hours"] += dur
            elif e["status"] == "sleeper":
                totals["sleeper_hours"] += dur

        output.append(
            {
                "date": date_key,
                "entries": entries,
                "totals": {k: round(v, 2) for k, v in totals.items()},
            }
        )

    return output


# ── Public entry point ────────────────────────────────────────────────────────
def build_trip_schedule(
    current_cycle_used_hours: float,
    current_to_pickup_miles: float,
    pickup_to_dropoff_miles: float,
    current_location: str,
    pickup_location: str,
    dropoff_location: str,
    prior_8_day_on_duty_hours: list[float] | None = None,
) -> dict[str, Any]:
    """
    Plan a full trip and return:
      - segments    : flat list of all duty events with timestamps
      - daily_logs  : per-day ELD log sheet data
      - trip_totals : summary metrics
    """
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    # Seed the 8-day rolling cycle.
    if prior_8_day_on_duty_hours and len(prior_8_day_on_duty_hours) == CYCLE_DAYS:
        cycle_seed = [max(0.0, float(v)) for v in prior_8_day_on_duty_hours]
    else:
        # Distribute evenly when detailed recap is unavailable.
        per_day = max(0.0, float(current_cycle_used_hours)) / CYCLE_DAYS
        cycle_seed = [per_day] * CYCLE_DAYS

    state = HosState(cycle=cycle_seed)
    segments: list[dict[str, Any]] = []
    total_miles = current_to_pickup_miles + pickup_to_dropoff_miles
    miles_since_fuel = 0.0

    # ── Leg 1: current location → pickup ─────────────────────────────────
    if current_to_pickup_miles > 0:
        now, miles_since_fuel = _drive(
            current_to_pickup_miles,
            now,
            state,
            segments,
            current_location,
            "Driving to pickup",
            miles_since_fuel,
        )

    # ── Pickup stop (1 h on-duty) ─────────────────────────────────────────
    now = _on_duty_stop(now, state, segments, pickup_location, "Pickup – 1 h on-duty (§spec)")

    # ── Leg 2: pickup → dropoff ───────────────────────────────────────────
    if pickup_to_dropoff_miles > 0:
        now, miles_since_fuel = _drive(
            pickup_to_dropoff_miles,
            now,
            state,
            segments,
            pickup_location,
            "Driving to dropoff",
            miles_since_fuel,
        )

    # ── Dropoff stop (1 h on-duty) ────────────────────────────────────────
    now = _on_duty_stop(now, state, segments, dropoff_location, "Dropoff – 1 h on-duty (§spec)")

    # ── Trip complete ─────────────────────────────────────────────────────
    _seg(
        segments,
        now,
        now + timedelta(hours=1),
        "off_duty",
        dropoff_location,
        "Trip complete – off duty",
    )

    return {
        "segments": segments,
        "daily_logs": _daily_logs(segments),
        "trip_totals": {
            "total_miles": round(total_miles, 2),
            "projected_cycle_used": round(state.cycle_used, 2),
        },
    }
