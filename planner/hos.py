from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


DRIVING_LIMIT_HOURS = 11.0
DUTY_WINDOW_HOURS = 14.0
BREAK_TRIGGER_HOURS = 8.0
CYCLE_LIMIT_HOURS = 70.0

AVG_SPEED_MPH = 55.0


@dataclass
class DutyState:
    driving_today: float = 0.0
    duty_window_used: float = 0.0
    driving_since_break: float = 0.0
    cycle_used: float = 0.0


def _status_for_activity(activity_type: str) -> str:
    if activity_type == "drive":
        return "driving"
    if activity_type == "sleeper":
        return "sleeper"
    if activity_type == "off_duty":
        return "off_duty"
    return "on_duty_not_driving"


def _append_segment(
    segments: list[dict[str, Any]],
    start: datetime,
    end: datetime,
    activity_type: str,
    location: str,
    notes: str,
) -> None:
    if end <= start:
        return
    segments.append(
        {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "activity_type": activity_type,
            "status": _status_for_activity(activity_type),
            "location": location,
            "notes": notes,
            "hours": round((end - start).total_seconds() / 3600, 2),
        }
    )


def _apply_duty_time(state: DutyState, hours: float, drives: bool) -> None:
    if drives:
        state.driving_today += hours
        state.driving_since_break += hours
    state.duty_window_used += hours
    state.cycle_used += hours


def _start_new_day(state: DutyState) -> None:
    state.driving_today = 0.0
    state.duty_window_used = 0.0
    state.driving_since_break = 0.0


def _ensure_capacity(
    state: DutyState,
    now: datetime,
    segments: list[dict[str, Any]],
    location: str,
) -> datetime:
    if state.cycle_used >= CYCLE_LIMIT_HOURS:
        reset_end = now + timedelta(hours=34)
        _append_segment(segments, now, reset_end, "off_duty", location, "34-hour restart")
        state.cycle_used = 0.0
        _start_new_day(state)
        return reset_end

    if state.driving_since_break >= BREAK_TRIGGER_HOURS:
        break_end = now + timedelta(minutes=30)
        _append_segment(segments, now, break_end, "on_duty", location, "30-minute break")
        _apply_duty_time(state, 0.5, drives=False)
        state.driving_since_break = 0.0
        now = break_end

    if state.driving_today >= DRIVING_LIMIT_HOURS or state.duty_window_used >= DUTY_WINDOW_HOURS:
        rest_end = now + timedelta(hours=10)
        _append_segment(segments, now, rest_end, "sleeper", location, "10-hour reset")
        _start_new_day(state)
        return rest_end

    return now


def _drive_leg(
    miles: float,
    now: datetime,
    state: DutyState,
    segments: list[dict[str, Any]],
    location: str,
    label: str,
    miles_since_last_fuel: float,
) -> tuple[datetime, float]:
    remaining_miles = miles
    while remaining_miles > 0:
        now = _ensure_capacity(state, now, segments, location)

        max_drive_by_11 = max(0.0, DRIVING_LIMIT_HOURS - state.driving_today)
        max_drive_by_14 = max(0.0, DUTY_WINDOW_HOURS - state.duty_window_used)
        max_drive_by_break = max(0.0, BREAK_TRIGGER_HOURS - state.driving_since_break)
        max_drive_by_cycle = max(0.0, CYCLE_LIMIT_HOURS - state.cycle_used)
        chunk_hours = min(max_drive_by_11, max_drive_by_14, max_drive_by_break, max_drive_by_cycle)

        if chunk_hours <= 0:
            now = _ensure_capacity(state, now, segments, location)
            continue

        chunk_miles = min(remaining_miles, chunk_hours * AVG_SPEED_MPH)
        drive_hours = chunk_miles / AVG_SPEED_MPH

        end = now + timedelta(hours=drive_hours)
        _append_segment(segments, now, end, "drive", location, f"{label} driving")
        _apply_duty_time(state, drive_hours, drives=True)
        remaining_miles -= chunk_miles
        miles_since_last_fuel += chunk_miles
        now = end

        if miles_since_last_fuel >= 1000:
            # Keep fueling cadence realistic for long-haul trips.
            now = _add_duty_stop(now, state, segments, location, "Fuel stop", hours=0.5)
            miles_since_last_fuel = 0.0

    return now, miles_since_last_fuel


def _add_duty_stop(
    now: datetime,
    state: DutyState,
    segments: list[dict[str, Any]],
    location: str,
    label: str,
    hours: float = 1.0,
) -> datetime:
    now = _ensure_capacity(state, now, segments, location)
    end = now + timedelta(hours=hours)
    _append_segment(segments, now, end, "on_duty", location, label)
    _apply_duty_time(state, hours, drives=False)
    return end


def _daily_logs(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_day: dict[str, list[dict[str, Any]]] = {}
    for segment in segments:
        start = datetime.fromisoformat(segment["start"])
        end = datetime.fromisoformat(segment["end"])
        pointer = start
        while pointer < end:
            day_start = datetime(pointer.year, pointer.month, pointer.day, tzinfo=pointer.tzinfo)
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
        totals = {
            "driving_hours": 0.0,
            "on_duty_hours": 0.0,
            "off_duty_hours": 0.0,
            "sleeper_hours": 0.0,
        }
        for entry in entries:
            duration = entry["end_hour"] - entry["start_hour"]
            if entry["status"] == "driving":
                totals["driving_hours"] += duration
                totals["on_duty_hours"] += duration
            elif entry["status"] == "on_duty_not_driving":
                totals["on_duty_hours"] += duration
            elif entry["status"] == "off_duty":
                totals["off_duty_hours"] += duration
            elif entry["status"] == "sleeper":
                totals["sleeper_hours"] += duration

        output.append(
            {
                "date": date_key,
                "entries": entries,
                "totals": {k: round(v, 2) for k, v in totals.items()},
            }
        )

    return output


def build_trip_schedule(
    current_cycle_used_hours: float,
    current_to_pickup_miles: float,
    pickup_to_dropoff_miles: float,
    current_location: str,
    pickup_location: str,
    dropoff_location: str,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    state = DutyState(cycle_used=max(0.0, current_cycle_used_hours))
    segments: list[dict[str, Any]] = []

    total_miles = current_to_pickup_miles + pickup_to_dropoff_miles
    miles_since_last_fuel = 0.0

    if current_to_pickup_miles > 0:
        now, miles_since_last_fuel = _drive_leg(
            current_to_pickup_miles,
            now,
            state,
            segments,
            current_location,
            "To pickup",
            miles_since_last_fuel,
        )

    now = _add_duty_stop(now, state, segments, pickup_location, "Pickup (1 hour)", hours=1.0)

    if pickup_to_dropoff_miles > 0:
        now, miles_since_last_fuel = _drive_leg(
            pickup_to_dropoff_miles,
            now,
            state,
            segments,
            pickup_location,
            "To dropoff",
            miles_since_last_fuel,
        )

    now = _add_duty_stop(now, state, segments, dropoff_location, "Dropoff (1 hour)", hours=1.0)
    _append_segment(
        segments,
        now,
        now + timedelta(hours=1),
        "off_duty",
        dropoff_location,
        "Trip complete / off duty",
    )

    return {
        "segments": segments,
        "daily_logs": _daily_logs(segments),
        "trip_totals": {
            "total_miles": round(total_miles, 2),
            "projected_cycle_used": round(state.cycle_used, 2),
        },
    }
