from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Count, Max, OuterRef, Q, Subquery
from django.db.models.functions import ExtractYear
from django.utils import timezone

from .models import Axis, Dimension, Indicator, Measurement


class FilterValidationError(ValueError):
    pass


@dataclass(frozen=True)
class DashboardFilters:
    year: int | None = None
    dimension: str = ""
    axis: str = ""
    q: str = ""

    def as_dict(self):
        return {
            "year": self.year,
            "dimension": self.dimension or None,
            "axis": self.axis or None,
            "q": self.q or None,
        }


def parse_dashboard_filters(params):
    raw_year = str(params.get("year") or "").strip()
    if raw_year.lower() in {"", "all", "todos"}:
        year = None
    else:
        try:
            year = int(raw_year)
        except (TypeError, ValueError) as error:
            raise FilterValidationError("O filtro year deve ser um ano válido.") from error
        if year < 1900 or year > 2200:
            raise FilterValidationError("O filtro year deve estar entre 1900 e 2200.")

    dimension = str(params.get("dimension") or "").strip()
    axis = str(params.get("axis") or "").strip()
    query = str(params.get("q") or "").strip()
    if len(dimension) > 200 or len(axis) > 220:
        raise FilterValidationError("Os identificadores de dimensão/eixo são inválidos.")
    if len(query) > 200:
        raise FilterValidationError("O filtro q aceita no máximo 200 caracteres.")

    return DashboardFilters(year=year, dimension=dimension, axis=axis, q=query)


def _reference_q(prefix, reference):
    if reference.isdecimal():
        return Q(**{f"{prefix}_id": int(reference)})
    return Q(**{f"{prefix}__slug__iexact": reference})


def filtered_indicators(filters):
    queryset = (
        Indicator.objects.select_related("axis__dimension")
        .filter(is_active=True, axis__is_active=True, axis__dimension__is_active=True)
        .order_by(
            "axis__dimension__display_order",
            "axis__display_order",
            "display_order",
            "name",
            "pk",
        )
    )
    if filters.dimension:
        queryset = queryset.filter(_reference_q("axis__dimension", filters.dimension))
    if filters.axis:
        queryset = queryset.filter(_reference_q("axis", filters.axis))
    if filters.q:
        queryset = queryset.filter(
            Q(name__icontains=filters.q)
            | Q(slug__icontains=filters.q)
            | Q(description__icontains=filters.q)
            | Q(methodology__icontains=filters.q)
            | Q(unit__icontains=filters.q)
            | Q(source_name__icontains=filters.q)
            | Q(axis__name__icontains=filters.q)
            | Q(axis__dimension__name__icontains=filters.q)
        )
    return queryset


def _measurement_order(queryset):
    return queryset.order_by("-period_end", "-period_start", "-updated_at", "-pk")


def with_measurement_references(indicator_queryset, year=None):
    current = Measurement.objects.filter(indicator_id=OuterRef("pk"))
    if year is not None:
        current = current.filter(period_end__year=year)
    current = _measurement_order(current)

    queryset = indicator_queryset.annotate(
        current_measurement_id=Subquery(current.values("pk")[:1]),
        current_period_end=Subquery(current.values("period_end")[:1]),
    )
    previous = _measurement_order(
        Measurement.objects.filter(
            indicator_id=OuterRef("pk"),
            period_end__lt=OuterRef("current_period_end"),
        )
    )
    return queryset.annotate(previous_measurement_id=Subquery(previous.values("pk")[:1]))


def load_referenced_measurements(indicators):
    measurement_ids = {
        measurement_id
        for indicator in indicators
        for measurement_id in (
            getattr(indicator, "current_measurement_id", None),
            getattr(indicator, "previous_measurement_id", None),
        )
        if measurement_id
    }
    if not measurement_ids:
        return {}
    return {
        measurement.pk: measurement
        for measurement in Measurement.objects.select_related("indicator").filter(pk__in=measurement_ids)
    }


def available_years(indicator_queryset):
    return list(
        Measurement.objects.filter(indicator_id__in=indicator_queryset.values("pk"))
        .annotate(year=ExtractYear("period_end"))
        .order_by("-year")
        .values_list("year", flat=True)
        .distinct()
    )


def _decimal_exact(value):
    if value is None:
        return None
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _decimal_number(value):
    if value is None:
        return None
    return float(value)


def _decimal_pair(value):
    return {
        "value": _decimal_number(value),
        "exact": _decimal_exact(value),
    }


def serialize_measurement(measurement):
    if measurement is None:
        return None
    return {
        "id": measurement.pk,
        "period_start": measurement.period_start.isoformat(),
        "period_end": measurement.period_end.isoformat(),
        "year": measurement.period_end.year,
        "value": _decimal_number(measurement.value),
        "value_exact": _decimal_exact(measurement.value),
        "target_value": _decimal_number(measurement.target_value),
        "target_value_exact": _decimal_exact(measurement.target_value),
        "effective_target_value": _decimal_number(measurement.effective_target_value),
        "effective_target_value_exact": _decimal_exact(measurement.effective_target_value),
        "quality": {
            "code": measurement.quality,
            "label": measurement.get_quality_display(),
        },
        "source": {
            "name": measurement.effective_source_name,
            "url": measurement.effective_source_url,
        },
        "observed_at": measurement.observed_at.isoformat(),
        "created_at": measurement.created_at.isoformat(),
        "updated_at": measurement.updated_at.isoformat(),
        "breakdown": measurement.breakdown,
        "note": measurement.note,
    }


def derive_status(indicator, current, previous=None):
    if current is None:
        return {
            "code": "no_data",
            "label": "Sem dados",
            "tone": "neutral",
            "target_met": None,
            "delta": None,
            "delta_exact": None,
            "delta_percentage": None,
        }

    target = current.effective_target_value
    target_met = None
    if target is not None:
        if indicator.polarity == Indicator.Polarity.HIGHER_IS_BETTER:
            target_met = current.value >= target
        elif indicator.polarity == Indicator.Polarity.LOWER_IS_BETTER:
            target_met = current.value <= target
        else:
            target_met = current.value == target

    delta = current.value - previous.value if previous is not None else None
    delta_percentage = None
    if delta is not None and previous.value != 0:
        delta_percentage = (delta / abs(previous.value)) * Decimal("100")

    if target_met is True:
        code, label, tone = "target_met", "Meta atingida", "positive"
    elif previous is None:
        if target is not None:
            code, label, tone = "target_not_met", "Meta ainda não atingida", "warning"
        else:
            code, label, tone = "no_reference", "Sem referência anterior", "neutral"
    elif delta == 0:
        code, label, tone = "stable", "Estável", "neutral"
    elif indicator.polarity == Indicator.Polarity.HIGHER_IS_BETTER:
        if delta > 0:
            code, label, tone = "improving", "Em melhora", "positive"
        else:
            code, label, tone = "worsening", "Em atenção", "negative"
    elif indicator.polarity == Indicator.Polarity.LOWER_IS_BETTER:
        if delta < 0:
            code, label, tone = "improving", "Em melhora", "positive"
        else:
            code, label, tone = "worsening", "Em atenção", "negative"
    else:
        code, label, tone = "changed", "Alteração registrada", "info"

    return {
        "code": code,
        "label": label,
        "tone": tone,
        "target_met": target_met,
        "delta": _decimal_number(delta),
        "delta_exact": _decimal_exact(delta),
        "delta_percentage": _decimal_number(delta_percentage),
    }


def serialize_indicator(indicator, current=None, previous=None):
    effective_target = current.effective_target_value if current is not None else indicator.target_value
    return {
        "id": indicator.pk,
        "slug": indicator.slug,
        "name": indicator.name,
        "description": indicator.description,
        "methodology": indicator.methodology,
        "unit": indicator.unit,
        "display_order": indicator.display_order,
        "kind": {
            "code": indicator.kind,
            "label": indicator.get_kind_display(),
        },
        "polarity": {
            "code": indicator.polarity,
            "label": indicator.get_polarity_display(),
        },
        "frequency": {
            "code": indicator.frequency,
            "label": indicator.get_frequency_display(),
        },
        "dimension": {
            "id": indicator.axis.dimension_id,
            "slug": indicator.axis.dimension.slug,
            "name": indicator.axis.dimension.name,
        },
        "axis": {
            "id": indicator.axis_id,
            "slug": indicator.axis.slug,
            "name": indicator.axis.name,
        },
        "target": {
            "default_value": _decimal_number(indicator.target_value),
            "default_value_exact": _decimal_exact(indicator.target_value),
            "effective_value": _decimal_number(effective_target),
            "effective_value_exact": _decimal_exact(effective_target),
            "deadline": indicator.target_deadline.isoformat() if indicator.target_deadline else None,
        },
        "source": {
            "name": indicator.source_name,
            "url": indicator.source_url,
        },
        "current_measurement": serialize_measurement(current),
        "previous_measurement": serialize_measurement(previous),
        "status": derive_status(indicator, current, previous),
    }


def taxonomy_payload(filters):
    dimensions = (
        Dimension.objects.filter(is_active=True)
        .annotate(
            indicator_count=Count(
                "axes__indicators",
                filter=Q(axes__is_active=True, axes__indicators__is_active=True),
                distinct=True,
            ),
            axis_count=Count("axes", filter=Q(axes__is_active=True), distinct=True),
        )
        .order_by("display_order", "name", "pk")
    )
    axes = (
        Axis.objects.select_related("dimension")
        .filter(is_active=True, dimension__is_active=True)
        .annotate(
            indicator_count=Count(
                "indicators",
                filter=Q(indicators__is_active=True),
                distinct=True,
            )
        )
        .order_by("dimension__display_order", "display_order", "name", "pk")
    )
    if filters.dimension:
        axes = axes.filter(_reference_q("dimension", filters.dimension))

    return {
        "dimensions": [
            {
                "id": dimension.pk,
                "slug": dimension.slug,
                "name": dimension.name,
                "description": dimension.description,
                "accent_color": dimension.accent_color,
                "icon_name": dimension.icon_name,
                "display_order": dimension.display_order,
                "axis_count": dimension.axis_count,
                "indicator_count": dimension.indicator_count,
            }
            for dimension in dimensions
        ],
        "axes": [
            {
                "id": axis.pk,
                "slug": axis.slug,
                "name": axis.name,
                "description": axis.description,
                "display_order": axis.display_order,
                "dimension": {
                    "id": axis.dimension_id,
                    "slug": axis.dimension.slug,
                    "name": axis.dimension.name,
                },
                "indicator_count": axis.indicator_count,
            }
            for axis in axes
        ],
    }


def overview_snapshot(filters):
    indicator_queryset = filtered_indicators(filters)
    years = available_years(indicator_queryset)
    indicators = list(with_measurement_references(indicator_queryset, filters.year))
    measurement_map = load_referenced_measurements(indicators)
    serialized_indicators = []
    with_data = 0
    for indicator in indicators:
        current = measurement_map.get(indicator.current_measurement_id)
        previous = measurement_map.get(indicator.previous_measurement_id)
        if current is not None:
            with_data += 1
        serialized_indicators.append(serialize_indicator(indicator, current, previous))

    indicator_ids = [indicator.pk for indicator in indicators]
    measurement_scope = Measurement.objects.filter(indicator_id__in=indicator_ids)
    if filters.year is not None:
        measurement_scope = measurement_scope.filter(period_end__year=filters.year)
    measurement_summary = measurement_scope.aggregate(
        count=Count("pk"),
        latest_update=Max("updated_at"),
    )

    total = len(indicators)
    dimension_count = len({indicator.axis.dimension_id for indicator in indicators})
    axis_count = len({indicator.axis_id for indicator in indicators})
    taxonomy = taxonomy_payload(filters)
    return {
        "generated_at": timezone.now().isoformat(),
        "filters": filters.as_dict(),
        "years": years,
        "dimensions": taxonomy["dimensions"],
        "axes": taxonomy["axes"],
        "indicators": serialized_indicators,
        "counts": {
            "dimensions": dimension_count,
            "axes": axis_count,
            "indicators": total,
            "indicators_with_data": with_data,
            "indicators_without_data": total - with_data,
            "measurements": measurement_summary["count"],
        },
        "coverage": {
            "with_data": with_data,
            "total": total,
            "percentage": round((with_data / total) * 100, 2) if total else 0,
        },
        "latest_update": (
            measurement_summary["latest_update"].isoformat()
            if measurement_summary["latest_update"]
            else None
        ),
    }


def parse_detail_filters(params):
    filters = parse_dashboard_filters({"year": params.get("year")})

    def parse_date_param(name):
        from django.utils.dateparse import parse_date

        raw_value = str(params.get(name) or "").strip()
        if not raw_value:
            return None
        value = parse_date(raw_value)
        if value is None:
            raise FilterValidationError(f"O filtro {name} deve usar o formato AAAA-MM-DD.")
        return value

    start = parse_date_param("start")
    end = parse_date_param("end")
    if start and end and end < start:
        raise FilterValidationError("O filtro end não pode ser anterior a start.")

    raw_limit = str(params.get("limit") or "500").strip()
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError) as error:
        raise FilterValidationError("O filtro limit deve ser um número inteiro.") from error
    if limit < 1 or limit > 5000:
        raise FilterValidationError("O filtro limit deve estar entre 1 e 5000.")
    return filters.year, start, end, limit


def indicator_detail_snapshot(indicator, *, year=None, start=None, end=None, limit=500):
    measurements = indicator.measurements.all()
    if year is not None:
        measurements = measurements.filter(period_end__year=year)
    if start is not None:
        measurements = measurements.filter(period_end__gte=start)
    if end is not None:
        measurements = measurements.filter(period_start__lte=end)

    total = measurements.count()
    selected = list(
        measurements.order_by("-period_end", "-period_start", "-updated_at", "-pk")[:limit]
    )
    selected.reverse()
    current = selected[-1] if selected else None
    if len(selected) >= 2:
        previous = selected[-2]
    elif current is not None:
        previous = (
            indicator.measurements.filter(period_end__lt=current.period_end)
            .order_by("-period_end", "-period_start", "-updated_at", "-pk")
            .first()
        )
    else:
        previous = None

    years = list(
        indicator.measurements.annotate(year=ExtractYear("period_end"))
        .order_by("-year")
        .values_list("year", flat=True)
        .distinct()
    )
    return {
        "generated_at": timezone.now().isoformat(),
        "filters": {
            "year": year,
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
            "limit": limit,
        },
        "years": years,
        "indicator": serialize_indicator(indicator, current, previous),
        "measurements": [serialize_measurement(measurement) for measurement in selected],
        "count": total,
        "returned": len(selected),
        "truncated": total > len(selected),
    }


FRESHNESS_HOURS = {
    Indicator.Frequency.REAL_TIME: 1,
    Indicator.Frequency.DAILY: 48,
    Indicator.Frequency.WEEKLY: 24 * 14,
    Indicator.Frequency.MONTHLY: 24 * 62,
    Indicator.Frequency.QUARTERLY: 24 * 180,
    Indicator.Frequency.SEMIANNUAL: 24 * 370,
    Indicator.Frequency.ANNUAL: 24 * 730,
    Indicator.Frequency.IRREGULAR: None,
}


def freshness_snapshot(filters):
    indicators = list(with_measurement_references(filtered_indicators(filters), filters.year))
    measurement_map = load_referenced_measurements(indicators)
    now = timezone.now()
    counts = {"fresh": 0, "stale": 0, "unknown": 0, "no_data": 0}
    rows = []
    latest_update = None

    for indicator in indicators:
        measurement = measurement_map.get(indicator.current_measurement_id)
        threshold_hours = FRESHNESS_HOURS[indicator.frequency]
        if measurement is None:
            status = "no_data"
            age_seconds = None
        else:
            if latest_update is None or measurement.updated_at > latest_update:
                latest_update = measurement.updated_at
            age_seconds = max(0, int((now - measurement.updated_at).total_seconds()))
            if threshold_hours is None:
                status = "unknown"
            elif age_seconds <= threshold_hours * 3600:
                status = "fresh"
            else:
                status = "stale"
        counts[status] += 1
        rows.append(
            {
                "indicator": {
                    "id": indicator.pk,
                    "slug": indicator.slug,
                    "name": indicator.name,
                },
                "dimension": {
                    "id": indicator.axis.dimension_id,
                    "slug": indicator.axis.dimension.slug,
                    "name": indicator.axis.dimension.name,
                },
                "axis": {
                    "id": indicator.axis_id,
                    "slug": indicator.axis.slug,
                    "name": indicator.axis.name,
                },
                "frequency": {
                    "code": indicator.frequency,
                    "label": indicator.get_frequency_display(),
                },
                "status": status,
                "age_seconds": age_seconds,
                "stale_after_seconds": threshold_hours * 3600 if threshold_hours is not None else None,
                "latest_period_end": measurement.period_end.isoformat() if measurement else None,
                "last_updated_at": measurement.updated_at.isoformat() if measurement else None,
            }
        )

    return {
        "generated_at": now.isoformat(),
        "filters": filters.as_dict(),
        "latest_update": latest_update.isoformat() if latest_update else None,
        "counts": {
            "indicators": len(indicators),
            **counts,
        },
        "indicators": rows,
    }
