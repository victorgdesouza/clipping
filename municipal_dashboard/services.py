from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from .models import Indicator, Measurement


MAX_MEASUREMENTS_PER_REQUEST = 500

ALLOWED_MEASUREMENT_FIELDS = {
    "indicator",
    "indicator_id",
    "indicator_slug",
    "period_start",
    "period_end",
    "value",
    "target_value",
    "quality",
    "source_name",
    "source_url",
    "observed_at",
    "breakdown",
    "note",
}


class MeasurementPayloadError(ValueError):
    def __init__(self, message, *, index=None, field=None):
        super().__init__(message)
        self.index = index
        self.field = field

    def as_dict(self):
        payload = {"error": str(self)}
        if self.index is not None:
            payload["index"] = self.index
        if self.field:
            payload["field"] = self.field
        return payload


@dataclass
class PreparedMeasurement:
    indicator: Indicator
    period_start: object
    period_end: object
    create_values: dict
    update_values: dict

    @property
    def natural_key(self):
        return self.indicator_id, self.period_start, self.period_end

    @property
    def indicator_id(self):
        return self.indicator.pk


def normalize_measurement_items(payload):
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict) and "measurements" in payload:
        extra_fields = set(payload) - {"measurements"}
        if extra_fields:
            raise MeasurementPayloadError(
                f"Campos não reconhecidos no envelope: {', '.join(sorted(extra_fields))}."
            )
        items = payload["measurements"]
    elif isinstance(payload, dict):
        items = [payload]
    else:
        raise MeasurementPayloadError("Envie um objeto, uma lista ou um objeto com a chave measurements.")

    if not isinstance(items, list):
        raise MeasurementPayloadError("A chave measurements deve conter uma lista.")
    if not items:
        raise MeasurementPayloadError("Envie pelo menos uma medição.")
    if len(items) > MAX_MEASUREMENTS_PER_REQUEST:
        raise MeasurementPayloadError(
            f"Cada requisição aceita no máximo {MAX_MEASUREMENTS_PER_REQUEST} medições."
        )
    return items


def _parse_indicator(item, index):
    references = [
        ("indicator_id", item.get("indicator_id")),
        ("indicator_slug", item.get("indicator_slug")),
        ("indicator", item.get("indicator")),
    ]
    supplied = [(name, value) for name, value in references if value not in (None, "")]
    if len(supplied) != 1:
        raise MeasurementPayloadError(
            "Informe exatamente um de indicator_id, indicator_slug ou indicator.",
            index=index,
            field="indicator",
        )

    field, reference = supplied[0]
    try:
        if field == "indicator_id" or (field == "indicator" and str(reference).isdecimal()):
            return Indicator.objects.select_related("axis__dimension").get(pk=int(reference))
        return Indicator.objects.select_related("axis__dimension").get(slug=str(reference).strip())
    except (TypeError, ValueError, Indicator.DoesNotExist) as error:
        raise MeasurementPayloadError(
            "Indicador não encontrado.",
            index=index,
            field=field,
        ) from error


def _parse_period(item, index, field):
    raw_value = item.get(field)
    value = parse_date(str(raw_value or "").strip())
    if value is None:
        raise MeasurementPayloadError(
            f"{field} deve usar o formato AAAA-MM-DD.",
            index=index,
            field=field,
        )
    return value


def _clean_decimal(field_name, raw_value, *, index, required=False):
    if raw_value in (None, ""):
        if required:
            raise MeasurementPayloadError(
                f"{field_name} é obrigatório.",
                index=index,
                field=field_name,
            )
        return None
    model_field = Measurement._meta.get_field(field_name)
    try:
        return model_field.clean(raw_value, None)
    except ValidationError as error:
        message = "; ".join(error.messages)
        raise MeasurementPayloadError(message, index=index, field=field_name) from error


def _parse_observed_at(raw_value, index):
    value = parse_datetime(str(raw_value or "").strip())
    if value is None:
        raise MeasurementPayloadError(
            "observed_at deve usar um datetime ISO 8601.",
            index=index,
            field="observed_at",
        )
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_current_timezone())
    return value


def prepare_measurement(item, index):
    if not isinstance(item, dict):
        raise MeasurementPayloadError("Cada medição deve ser um objeto JSON.", index=index)
    unknown_fields = set(item) - ALLOWED_MEASUREMENT_FIELDS
    if unknown_fields:
        raise MeasurementPayloadError(
            f"Campos não reconhecidos: {', '.join(sorted(unknown_fields))}.",
            index=index,
        )

    indicator = _parse_indicator(item, index)
    period_start = _parse_period(item, index, "period_start")
    period_end = _parse_period(item, index, "period_end")
    if period_end < period_start:
        raise MeasurementPayloadError(
            "period_end não pode ser anterior a period_start.",
            index=index,
            field="period_end",
        )

    value = _clean_decimal("value", item.get("value"), index=index, required=True)
    create_values = {
        "value": value,
        "target_value": None,
        "quality": Measurement.Quality.PROVISIONAL,
        "source_name": "",
        "source_url": "",
        "observed_at": timezone.now(),
        "breakdown": {},
        "note": "",
    }
    update_values = {"value": value}

    if "target_value" in item:
        target_value = _clean_decimal("target_value", item.get("target_value"), index=index)
        create_values["target_value"] = target_value
        update_values["target_value"] = target_value
    if "quality" in item:
        quality = str(item.get("quality") or "").strip()
        if quality not in Measurement.Quality.values:
            raise MeasurementPayloadError(
                f"quality deve ser uma destas opções: {', '.join(Measurement.Quality.values)}.",
                index=index,
                field="quality",
            )
        create_values["quality"] = quality
        update_values["quality"] = quality
    if "source_name" in item:
        source_name = str(item.get("source_name") or "").strip()
        create_values["source_name"] = source_name
        update_values["source_name"] = source_name
    if "source_url" in item:
        source_url = str(item.get("source_url") or "").strip()
        create_values["source_url"] = source_url
        update_values["source_url"] = source_url
    if "observed_at" in item:
        observed_at = _parse_observed_at(item.get("observed_at"), index)
        create_values["observed_at"] = observed_at
        update_values["observed_at"] = observed_at
    if "breakdown" in item:
        breakdown = item.get("breakdown")
        if not isinstance(breakdown, dict):
            raise MeasurementPayloadError(
                "breakdown deve ser um objeto JSON.",
                index=index,
                field="breakdown",
            )
        create_values["breakdown"] = breakdown
        update_values["breakdown"] = breakdown
    if "note" in item:
        note = str(item.get("note") or "")
        create_values["note"] = note
        update_values["note"] = note

    candidate = Measurement(
        indicator=indicator,
        period_start=period_start,
        period_end=period_end,
        **create_values,
    )
    try:
        candidate.full_clean(validate_unique=False, validate_constraints=False)
    except ValidationError as error:
        if hasattr(error, "message_dict"):
            field, messages = next(iter(error.message_dict.items()))
            message = "; ".join(messages)
        else:
            field, message = None, "; ".join(error.messages)
        raise MeasurementPayloadError(message, index=index, field=field) from error

    return PreparedMeasurement(
        indicator=indicator,
        period_start=period_start,
        period_end=period_end,
        create_values=create_values,
        update_values=update_values,
    )


def prepare_measurements(payload):
    items = normalize_measurement_items(payload)
    prepared = []
    natural_keys = set()
    for index, item in enumerate(items):
        measurement = prepare_measurement(item, index)
        if measurement.natural_key in natural_keys:
            raise MeasurementPayloadError(
                "A mesma combinação de indicador e período aparece mais de uma vez na requisição.",
                index=index,
            )
        natural_keys.add(measurement.natural_key)
        prepared.append(measurement)
    return prepared


@transaction.atomic
def upsert_measurements(prepared_measurements):
    result = {
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "measurements": [],
    }
    for prepared in prepared_measurements:
        measurement, created = Measurement.objects.select_for_update().get_or_create(
            indicator=prepared.indicator,
            period_start=prepared.period_start,
            period_end=prepared.period_end,
            defaults=prepared.create_values,
        )
        if created:
            result["created"] += 1
            action = "created"
        else:
            changed_fields = []
            for field, value in prepared.update_values.items():
                if getattr(measurement, field) != value:
                    setattr(measurement, field, value)
                    changed_fields.append(field)
            if changed_fields:
                try:
                    measurement.full_clean(validate_unique=False, validate_constraints=False)
                except ValidationError as error:
                    raise MeasurementPayloadError("; ".join(error.messages)) from error
                measurement.save(update_fields=[*changed_fields, "updated_at"])
                result["updated"] += 1
                action = "updated"
            else:
                result["unchanged"] += 1
                action = "unchanged"
        measurement.refresh_from_db()
        measurement.indicator = prepared.indicator
        measurement._upsert_action = action
        result["measurements"].append(measurement)
    return result
