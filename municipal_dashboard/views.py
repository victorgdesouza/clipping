import json

from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .models import Indicator
from .selectors import (
    FilterValidationError,
    freshness_snapshot,
    indicator_detail_snapshot,
    overview_snapshot,
    parse_dashboard_filters,
    parse_detail_filters,
    serialize_measurement,
)
from .services import MeasurementPayloadError, prepare_measurements, upsert_measurements


def _json_response(payload, *, status=200):
    response = JsonResponse(
        payload,
        status=status,
        json_dumps_params={"ensure_ascii": False},
    )
    response["Cache-Control"] = "no-store"
    return response


def _filter_error(error):
    return _json_response({"error": str(error)}, status=400)


@require_GET
@ensure_csrf_cookie
def dashboard(request):
    return render(
        request,
        "municipal_dashboard/dashboard.html",
        {
            "api_overview_url": reverse("municipal_dashboard:api_overview"),
            "api_freshness_url": reverse("municipal_dashboard:api_freshness"),
            "api_measurements_url": reverse("municipal_dashboard:api_measurements"),
        },
    )


@require_GET
def api_overview(request):
    try:
        filters = parse_dashboard_filters(request.GET)
    except FilterValidationError as error:
        return _filter_error(error)
    return _json_response(overview_snapshot(filters))


@require_GET
def api_indicator_detail(request, slug):
    try:
        indicator = Indicator.objects.select_related("axis__dimension").get(
            slug=slug,
            is_active=True,
            axis__is_active=True,
            axis__dimension__is_active=True,
        )
    except Indicator.DoesNotExist:
        return _json_response({"error": "Indicador não encontrado."}, status=404)
    try:
        year, start, end, limit = parse_detail_filters(request.GET)
    except FilterValidationError as error:
        return _filter_error(error)
    return _json_response(
        indicator_detail_snapshot(
            indicator,
            year=year,
            start=start,
            end=end,
            limit=limit,
        )
    )


@require_GET
def api_freshness(request):
    try:
        filters = parse_dashboard_filters(request.GET)
    except FilterValidationError as error:
        return _filter_error(error)
    return _json_response(freshness_snapshot(filters))


@require_POST
def api_measurements(request):
    if not request.user.is_authenticated:
        return _json_response({"error": "Autenticação obrigatória."}, status=401)
    if not request.user.is_staff:
        return _json_response({"error": "Apenas usuários da equipe podem inserir medições."}, status=403)
    if request.content_type != "application/json":
        return _json_response(
            {"error": "Use Content-Type: application/json."},
            status=415,
        )
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _json_response({"error": "JSON inválido."}, status=400)

    try:
        prepared = prepare_measurements(payload)
        result = upsert_measurements(prepared)
    except MeasurementPayloadError as error:
        return _json_response(error.as_dict(), status=400)

    serialized = []
    for measurement in result["measurements"]:
        item = serialize_measurement(measurement)
        item["action"] = measurement._upsert_action
        serialized.append(item)
    return _json_response(
        {
            "created": result["created"],
            "updated": result["updated"],
            "unchanged": result["unchanged"],
            "measurements": serialized,
        },
        status=201 if result["created"] else 200,
    )
