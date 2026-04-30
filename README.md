# Backend — Trip + ELD Planner API

Django REST Framework API that accepts trip inputs, geocodes locations, fetches road routes, and runs a FMCSA-compliant HOS scheduling engine to produce duty timelines and daily ELD log sheet data.

---

## Stack

| Layer | Technology |
|---|---|
| Web framework | Django 5.0 |
| REST API | Django REST Framework 3.15 |
| CORS | django-cors-headers |
| HTTP client | requests |
| Database | SQLite (local dev) — not used for trip data |
| Geocoding | Nominatim (OpenStreetMap) — free, no key needed |
| Routing | OSRM public API — free, no key needed |

---

## Project structure

```
backend/
├── manage.py
├── requirements.txt
├── db.sqlite3              # Django admin/auth only — trip data is stateless
├── truck_backend/
│   ├── settings.py
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
└── planner/
    ├── apps.py
    ├── urls.py
    ├── views.py            # POST /api/plan-trip/ endpoint + input validation
    ├── services.py         # Geocoding (Nominatim) + Routing (OSRM)
    ├── hos.py              # FMCSA HOS engine (core logic)
    └── test_hos.py         # Unit tests for the HOS engine
```

---

## Local setup

```bash
cd backend

# Create and activate virtual environment
python -m venv venv
source venv/Scripts/activate      # Windows
# source venv/bin/activate         # macOS / Linux

# Install dependencies
pip install -r requirements.txt

# Run Django migrations (only needed for Django admin/auth tables)
python manage.py migrate

# Start dev server
python manage.py runserver
```

API available at: `http://127.0.0.1:8000/api/plan-trip/`

---

## API reference

### `POST /api/plan-trip/`

**Request body**

```json
{
  "current_location": "Dallas, TX",
  "pickup_location": "Kansas City, MO",
  "dropoff_location": "Chicago, IL",
  "current_cycle_used_hours": 20,
  "prior_8_day_on_duty_hours": [8, 9, 8.5, 10, 7, 9.5, 6, 4]
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `current_location` | string | ✅ | Free-text location (city, state, address) |
| `pickup_location` | string | ✅ | Pickup point |
| `dropoff_location` | string | ✅ | Dropoff point |
| `current_cycle_used_hours` | float 0–70 | ✅ | Hours already used in current 70h cycle |
| `prior_8_day_on_duty_hours` | float[8] | ❌ | Per-day on-duty hours, oldest first — improves rolling recap accuracy |

**Response body**

```json
{
  "route": {
    "distance_miles": 891.4,
    "duration_hours": 14.2,
    "polyline": [[lat, lon], ...],
    "stops": [
      { "type": "current", "location": "...", "coordinates": [lat, lon] },
      { "type": "pickup",  "location": "...", "coordinates": [lat, lon] },
      { "type": "dropoff", "location": "...", "coordinates": [lat, lon] }
    ],
    "instructions": {
      "to_pickup":  [{ "instruction": "Turn right", "road": "I-35 N", "distance_miles": 12.3 }],
      "to_dropoff": [...]
    }
  },
  "schedule": [
    {
      "start": "2026-04-30T08:00:00+00:00",
      "end":   "2026-04-30T16:00:00+00:00",
      "activity_type": "driving",
      "status": "driving",
      "location": "...",
      "notes": "Driving to pickup",
      "hours": 8.0
    }
  ],
  "daily_logs": [
    {
      "date": "2026-04-30",
      "entries": [
        { "start_hour": 8.0, "end_hour": 16.0, "status": "driving", "notes": "..." }
      ],
      "totals": {
        "driving_hours": 8.0,
        "on_duty_not_driving_hours": 1.0,
        "off_duty_hours": 0.5,
        "sleeper_hours": 0.0
      }
    }
  ],
  "trip_totals": {
    "total_miles": 891.4,
    "projected_cycle_used": 31.5
  }
}
```

---

## HOS engine (`planner/hos.py`)

Implements FMCSA property-carrying driver rules (49 CFR Part 395):

| Rule | Limit | Regulation |
|---|---|---|
| Driving limit | 11 h per duty period | §395.3(a)(3) |
| Duty window | 14 consecutive clock hours from shift start | §395.3(a)(2) |
| Break requirement | 30-min break before exceeding 8 cumul. driving hours | §395.3(a)(3)(ii) |
| Daily reset | 10 consecutive off-duty/sleeper hours | §395.3(a)(1) |
| Cycle limit | 70 h on-duty in any rolling 8 consecutive days | §395.3(b) |
| Cycle restart | 34 consecutive off-duty hours resets 70h cycle | §395.3(c) |

**Key design guarantee:** `driving_capacity()` is computed before every drive chunk as `min(11h_remaining, 14h_remaining, 8h_break_remaining, 70h_remaining)`. Mandatory rests are inserted **before** each chunk, so no single driving segment can ever exceed any FMCSA limit.

### Running the tests

```bash
python test_hos.py
```

Expected output:

```
[PASS] test_break_at_8h
[PASS] test_no_segment_exceeds_8h
[PASS] test_34h_restart_on_high_cycle
[PASS] test_long_trip_multi_day
[PASS] test_break_resets_after_on_duty_stop
[PASS] test_cycle_rolling_advance

All HOS tests passed.
```

---

## Deployment

Deploy to any Django-compatible host: **Render**, **Railway**, or **Fly.io**.

```bash
# Production settings to set as environment variables:
SECRET_KEY=<strong-random-key>
DEBUG=False
ALLOWED_HOSTS=yourdomain.com
```

No database migrations are needed for the trip planner itself (trip data is fully stateless).
