from __future__ import annotations

from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .hos import build_trip_schedule
from .services import MapServiceError, geocode_location, route_between_points


class PlanTripInputSerializer(serializers.Serializer):
    current_location = serializers.CharField()
    pickup_location = serializers.CharField()
    dropoff_location = serializers.CharField()
    current_cycle_used_hours = serializers.FloatField(min_value=0, max_value=70)
    prior_8_day_on_duty_hours = serializers.ListField(
        child=serializers.FloatField(min_value=0),
        required=False,
        min_length=8,
        max_length=8,
    )

    def validate(self, attrs):
        locations = {
            attrs["current_location"].strip().lower(),
            attrs["pickup_location"].strip().lower(),
            attrs["dropoff_location"].strip().lower(),
        }
        if len(locations) < 3:
            raise serializers.ValidationError("Current, pickup, and dropoff locations must be different.")
        return attrs


class PlanTripView(APIView):
    @staticmethod
    def _format_steps(raw_steps):
        steps = []
        for step in raw_steps:
            maneuver = step.get("maneuver", {})
            modifier = maneuver.get("modifier", "")
            step_type = maneuver.get("type", "")
            name = step.get("name") or "unnamed road"
            distance_miles = round((step.get("distance", 0.0) or 0.0) * 0.000621371, 2)
            instruction = f'{step_type.replace("_", " ").title()} {modifier}'.strip()
            steps.append(
                {
                    "instruction": instruction if instruction else "Continue",
                    "road": name,
                    "distance_miles": distance_miles,
                }
            )
        return steps

    def post(self, request):
        serializer = PlanTripInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        try:
            current_point = geocode_location(payload["current_location"])
            pickup_point = geocode_location(payload["pickup_location"])
            dropoff_point = geocode_location(payload["dropoff_location"])

            leg_1 = route_between_points(current_point, pickup_point)
            leg_2 = route_between_points(pickup_point, dropoff_point)
        except MapServiceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        leg_1_miles = leg_1["distance_meters"] * 0.000621371
        leg_2_miles = leg_2["distance_meters"] * 0.000621371

        schedule = build_trip_schedule(
            current_cycle_used_hours=payload["current_cycle_used_hours"],
            current_to_pickup_miles=leg_1_miles,
            pickup_to_dropoff_miles=leg_2_miles,
            current_location=current_point["label"],
            pickup_location=pickup_point["label"],
            dropoff_location=dropoff_point["label"],
            prior_8_day_on_duty_hours=payload.get("prior_8_day_on_duty_hours"),
        )

        route_geo = [[coord[1], coord[0]] for coord in leg_1["geometry"] + leg_2["geometry"]]

        stops = [
            {
                "type": "current",
                "location": current_point["label"],
                "coordinates": [current_point["lat"], current_point["lon"]],
            },
            {
                "type": "pickup",
                "location": pickup_point["label"],
                "coordinates": [pickup_point["lat"], pickup_point["lon"]],
            },
            {
                "type": "dropoff",
                "location": dropoff_point["label"],
                "coordinates": [dropoff_point["lat"], dropoff_point["lon"]],
            },
        ]

        return Response(
            {
                "route": {
                    "distance_miles": round(leg_1_miles + leg_2_miles, 2),
                    "duration_hours": round((leg_1["duration_seconds"] + leg_2["duration_seconds"]) / 3600, 2),
                    "polyline": route_geo,
                    "stops": stops,
                    "instructions": {
                        "to_pickup": self._format_steps(leg_1.get("steps", [])),
                        "to_dropoff": self._format_steps(leg_2.get("steps", [])),
                    },
                },
                "schedule": schedule["segments"],
                "daily_logs": schedule["daily_logs"],
                "trip_totals": schedule["trip_totals"],
            }
        )
