"""Leitura, validação e importação idempotente de medições em CSV."""

import csv
import json
from pathlib import Path

from .models import Measurement
from .services import MeasurementPayloadError, prepare_measurement, upsert_measurements


CSV_FIELDS = (
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
)
REQUIRED_CSV_FIELDS = {
    "indicator_slug",
    "period_start",
    "period_end",
    "value",
}
JSON_FIELDS = {"breakdown"}


class MunicipalCSVImportError(ValueError):
    """Erro de estrutura ou validação associado a um CSV municipal."""

    def __init__(self, message, *, row_number=None):
        super().__init__(message)
        self.row_number = row_number

    def __str__(self):
        message = super().__str__()
        if self.row_number is None:
            return message
        return f"Linha {self.row_number}: {message}"


def _validate_headers(fieldnames):
    if not fieldnames:
        raise MunicipalCSVImportError("O arquivo não possui cabeçalho.")
    normalized = [str(field or "").strip() for field in fieldnames]
    if any(not field for field in normalized):
        raise MunicipalCSVImportError("O cabeçalho contém uma coluna sem nome.")
    duplicates = sorted({field for field in normalized if normalized.count(field) > 1})
    if duplicates:
        raise MunicipalCSVImportError(
            "Colunas repetidas no cabeçalho: " + ", ".join(duplicates) + "."
        )
    unknown = sorted(set(normalized) - set(CSV_FIELDS))
    if unknown:
        raise MunicipalCSVImportError(
            "Colunas não reconhecidas: " + ", ".join(unknown) + "."
        )
    missing = sorted(REQUIRED_CSV_FIELDS - set(normalized))
    if missing:
        raise MunicipalCSVImportError(
            "Colunas obrigatórias ausentes: " + ", ".join(missing) + "."
        )
    return normalized


def _row_to_payload(raw_row, row_number):
    if None in raw_row:
        raise MunicipalCSVImportError(
            "A linha possui mais valores que o cabeçalho.",
            row_number=row_number,
        )

    payload = {}
    for raw_field, raw_value in raw_row.items():
        field = str(raw_field).strip()
        value = "" if raw_value is None else str(raw_value).strip()
        if not value:
            continue
        if field in JSON_FIELDS:
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as error:
                raise MunicipalCSVImportError(
                    f"{field} deve conter JSON válido: {error.msg}.",
                    row_number=row_number,
                ) from error
            if not isinstance(parsed, dict):
                raise MunicipalCSVImportError(
                    f"{field} deve conter um objeto JSON.",
                    row_number=row_number,
                )
            payload[field] = parsed
        else:
            payload[field] = value

    missing_values = sorted(
        field for field in REQUIRED_CSV_FIELDS if field not in payload
    )
    if missing_values:
        raise MunicipalCSVImportError(
            "Valores obrigatórios ausentes: " + ", ".join(missing_values) + ".",
            row_number=row_number,
        )
    return payload


def prepare_csv_measurements(path):
    """Lê e valida integralmente um CSV antes de qualquer escrita."""

    csv_path = Path(path)
    if not csv_path.exists():
        raise MunicipalCSVImportError(f"Arquivo não encontrado: {csv_path}.")
    if not csv_path.is_file():
        raise MunicipalCSVImportError(f"O caminho não é um arquivo: {csv_path}.")

    prepared = []
    natural_keys = set()
    try:
        stream = csv_path.open("r", encoding="utf-8-sig", newline="")
    except (OSError, UnicodeError) as error:
        raise MunicipalCSVImportError(f"Não foi possível abrir o CSV: {error}.") from error

    with stream:
        reader = csv.DictReader(stream)
        _validate_headers(reader.fieldnames)
        for row_number, raw_row in enumerate(reader, start=2):
            if not any(str(value or "").strip() for value in raw_row.values()):
                continue
            payload = _row_to_payload(raw_row, row_number)
            try:
                item = prepare_measurement(payload, row_number)
            except MeasurementPayloadError as error:
                field_hint = f" ({error.field})" if error.field else ""
                raise MunicipalCSVImportError(
                    f"{error}{field_hint}",
                    row_number=row_number,
                ) from error
            if item.natural_key in natural_keys:
                raise MunicipalCSVImportError(
                    "A combinação de indicador e período está repetida no arquivo.",
                    row_number=row_number,
                )
            natural_keys.add(item.natural_key)
            prepared.append(item)

    if not prepared:
        raise MunicipalCSVImportError("O arquivo não contém linhas de dados.")
    return prepared


def _preview_upsert(prepared_measurements):
    result = {"created": 0, "updated": 0, "unchanged": 0}
    for prepared in prepared_measurements:
        measurement = Measurement.objects.filter(
            indicator=prepared.indicator,
            period_start=prepared.period_start,
            period_end=prepared.period_end,
        ).first()
        if measurement is None:
            result["created"] += 1
            continue
        if any(
            getattr(measurement, field) != value
            for field, value in prepared.update_values.items()
        ):
            result["updated"] += 1
        else:
            result["unchanged"] += 1
    return result


def import_measurements_csv(path, *, dry_run=False):
    """Valida o arquivo e cria/atualiza medições pela chave natural.

    No modo ``dry_run`` nenhuma escrita é executada. Campos opcionais vazios no
    CSV são ignorados, preservando o valor já existente no banco.
    """

    prepared = prepare_csv_measurements(path)
    if dry_run:
        result = _preview_upsert(prepared)
    else:
        raw_result = upsert_measurements(prepared)
        result = {
            "created": raw_result["created"],
            "updated": raw_result["updated"],
            "unchanged": raw_result["unchanged"],
        }
    return {
        "rows": len(prepared),
        "dry_run": dry_run,
        **result,
    }
