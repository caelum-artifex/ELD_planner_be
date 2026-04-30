"""Quick correctness tests for the HOS engine."""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "truck_backend.settings")

from planner.hos import build_trip_schedule, HosState, BREAK_AFTER

def test_break_at_8h():
    state = HosState()
    assert state.driving_capacity() == 8.0, f"expected 8.0 got {state.driving_capacity()}"

    state.add_driving(8.0)
    assert state.driving_capacity() == 0.0, f"expected 0.0 after 8h driving"
    assert state.needs_break(), "needs_break must be True at 8h"

    state.add_rest(0.5)
    cap = state.driving_capacity()
    assert cap == 3.0, f"expected 3.0 after break (11-8=3), got {cap}"
    print("[PASS] test_break_at_8h")


def test_no_segment_exceeds_8h():
    result = build_trip_schedule(
        current_cycle_used_hours=20,
        current_to_pickup_miles=500,
        pickup_to_dropoff_miles=800,
        current_location="Dallas, TX",
        pickup_location="Kansas City, MO",
        dropoff_location="Chicago, IL",
    )
    violations = [
        s for s in result["segments"]
        if s["activity_type"] == "drive" and s["hours"] > BREAK_AFTER + 0.001
    ]
    assert not violations, f"Driving segments exceed 8h: {violations}"
    print(f"[PASS] test_no_segment_exceeds_8h ({len(result['segments'])} segs)")


def test_34h_restart_on_high_cycle():
    result = build_trip_schedule(
        current_cycle_used_hours=68,
        current_to_pickup_miles=200,
        pickup_to_dropoff_miles=200,
        current_location="A",
        pickup_location="B",
        dropoff_location="C",
    )
    restarts = [s for s in result["segments"] if "34-hour" in s["notes"]]
    assert restarts, "Expected at least one 34h restart segment"
    print(f"[PASS] test_34h_restart_on_high_cycle ({len(restarts)} restart(s))")


def test_long_trip_multi_day():
    result = build_trip_schedule(
        current_cycle_used_hours=5,
        current_to_pickup_miles=200,
        pickup_to_dropoff_miles=1800,
        current_location="New York, NY",
        pickup_location="Chicago, IL",
        dropoff_location="Los Angeles, CA",
    )
    days = result["daily_logs"]
    assert len(days) >= 3, f"Expected 3+ daily logs for long trip, got {len(days)}"
    print(f"[PASS] test_long_trip_multi_day ({len(days)} log sheets)")


def test_break_resets_after_on_duty_stop():
    state = HosState()
    state.add_driving(7.5)
    assert state.hours_since_break == 7.5
    state.add_on_duty(1.0)   # 1h on-duty stop (pickup)
    assert state.hours_since_break == 0.0, "1h on-duty stop should reset break counter"
    print("[PASS] test_break_resets_after_on_duty_stop")


def test_cycle_rolling_advance():
    state = HosState(cycle=[8.0] * 8)
    assert state.cycle_used == 64.0
    state.daily_reset()
    assert state.cycle_used == 56.0, f"oldest day should drop off, got {state.cycle_used}"
    print("[PASS] test_cycle_rolling_advance")


if __name__ == "__main__":
    test_break_at_8h()
    test_no_segment_exceeds_8h()
    test_34h_restart_on_high_cycle()
    test_long_trip_multi_day()
    test_break_resets_after_on_duty_stop()
    test_cycle_rolling_advance()
    print()
    print("All HOS tests passed.")
