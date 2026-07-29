import csv
import json
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase

from municipal_dashboard.catalog import (
    AXES,
    DIMENSIONS,
    INDICATORS,
    MANDATORY_INDICATORS,
    PROPOSED_INDICATORS,
    SUPPLEMENTAL_INDICATORS,
)
from municipal_dashboard.importing import import_measurements_csv
from municipal_dashboard.models import Axis, Dimension, Indicator, Measurement
from municipal_dashboard.seeding import OFFICIAL_SEEDS, sync_catalog


class MunicipalCatalogTests(TestCase):
    def test_catalog_has_six_dimensions_twenty_two_axes_and_governed_indicator_kinds(self):
        self.assertEqual(len(DIMENSIONS), 6)
        self.assertEqual(len(AXES), 22)
        self.assertEqual([axis["number"] for axis in AXES], list(range(1, 23)))
        self.assertEqual(len(MANDATORY_INDICATORS), 64)
        self.assertEqual(len(PROPOSED_INDICATORS), 24)
        self.assertEqual(len(SUPPLEMENTAL_INDICATORS), 10)

        catalog_kinds = Counter(item["kind"] for item in INDICATORS)
        self.assertEqual(
            catalog_kinds,
            {
                Indicator.Kind.MANDATORY: 64,
                Indicator.Kind.TECHNICAL_PROPOSAL: 24,
                Indicator.Kind.SUPPLEMENTAL: 10,
            },
        )

    def test_catalog_sync_is_idempotent_and_never_overwrites_existing_seed_measurement(self):
        first = sync_catalog()

        self.assertEqual(Dimension.objects.count(), 6)
        self.assertEqual(Axis.objects.count(), 22)
        self.assertEqual(Indicator.objects.count(), 98)
        self.assertEqual(Measurement.objects.count(), 64)
        self.assertEqual(len(OFFICIAL_SEEDS), 64)
        self.assertEqual(first["dimensions"]["created"], 6)
        self.assertEqual(first["axes"]["created"], 22)
        self.assertEqual(first["indicators"]["created"], 98)
        self.assertEqual(first["measurements"]["created"], 64)
        self.assertEqual(
            Counter(Indicator.objects.values_list("kind", flat=True)),
            {
                Indicator.Kind.MANDATORY: 64,
                Indicator.Kind.TECHNICAL_PROPOSAL: 24,
                Indicator.Kind.SUPPLEMENTAL: 10,
            },
        )

        protected = Measurement.objects.get(
            indicator__slug="resultado-fiscal-consolidado-percentual",
            period_start=date(2024, 1, 1),
            period_end=date(2024, 12, 31),
        )
        protected.value = Decimal("999.99")
        protected.quality = Measurement.Quality.REVISED
        protected.breakdown = {"revisao_manual": True}
        protected.note = "Valor já revisado pelo gestor."
        protected.save(
            update_fields=("value", "quality", "breakdown", "note", "updated_at")
        )

        second = sync_catalog()
        protected.refresh_from_db()

        self.assertEqual(protected.value, Decimal("999.99"))
        self.assertEqual(protected.quality, Measurement.Quality.REVISED)
        self.assertEqual(protected.breakdown, {"revisao_manual": True})
        self.assertEqual(protected.note, "Valor já revisado pelo gestor.")
        self.assertEqual(Measurement.objects.count(), 64)
        self.assertEqual(
            second["measurements"],
            {"created": 0, "updated": 0, "unchanged": 64},
        )
        for group in ("dimensions", "axes", "indicators"):
            self.assertEqual(second[group]["created"], 0)
            self.assertEqual(second[group]["updated"], 0)
            self.assertGreater(second[group]["unchanged"], 0)

    def test_caged_2024_breakdown_is_reconciled_from_admissions_and_dismissals(self):
        sync_catalog()

        measurement = Measurement.objects.get(
            indicator__slug="saldo-empregos-formais",
            period_start=date(2024, 1, 1),
            period_end=date(2024, 12, 31),
        )
        breakdown = measurement.breakdown

        self.assertEqual(measurement.value, Decimal("5691"))
        self.assertEqual(breakdown["admissoes"], 92355)
        self.assertEqual(breakdown["desligamentos"], 86664)
        self.assertEqual(
            breakdown["admissoes"] - breakdown["desligamentos"],
            5691,
        )
        self.assertEqual(breakdown["saldo_reconciliado"], 5691)
        self.assertEqual(breakdown["saldo_total_setorial_impresso"], 4309)
        self.assertEqual(sum(breakdown["saldos_setoriais"].values()), 5691)
        self.assertIn("reconciliado", measurement.note)
        self.assertIn("p. 72", measurement.note)


class MunicipalCSVImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        sync_catalog(include_seeds=False)
        cls.indicator = Indicator.objects.get(slug="indice-transparencia-ativa")

    def _write_csv(self, directory, *, value):
        path = Path(directory) / "medicoes.csv"
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=(
                    "indicator_slug",
                    "period_start",
                    "period_end",
                    "value",
                    "quality",
                    "source_name",
                    "breakdown",
                ),
            )
            writer.writeheader()
            writer.writerow(
                {
                    "indicator_slug": self.indicator.slug,
                    "period_start": "2024-01-01",
                    "period_end": "2024-12-31",
                    "value": value,
                    "quality": Measurement.Quality.OFFICIAL,
                    "source_name": "Controladoria municipal",
                    "breakdown": json.dumps(
                        {"itens_publicados": 88, "itens_avaliados": 100},
                        ensure_ascii=False,
                    ),
                }
            )
        return path

    def test_csv_dry_run_writes_nothing_then_import_upserts_by_natural_key(self):
        with TemporaryDirectory() as directory:
            path = self._write_csv(directory, value="88")

            preview = import_measurements_csv(path, dry_run=True)
            self.assertEqual(
                preview,
                {
                    "rows": 1,
                    "dry_run": True,
                    "created": 1,
                    "updated": 0,
                    "unchanged": 0,
                },
            )
            self.assertFalse(Measurement.objects.exists())

            imported = import_measurements_csv(path)
            self.assertEqual(imported["created"], 1)
            self.assertEqual(imported["updated"], 0)
            self.assertEqual(Measurement.objects.count(), 1)

            unchanged = import_measurements_csv(path)
            self.assertEqual(unchanged["unchanged"], 1)
            self.assertEqual(Measurement.objects.count(), 1)

            path = self._write_csv(directory, value="91.25")
            updated = import_measurements_csv(path)
            self.assertEqual(updated["created"], 0)
            self.assertEqual(updated["updated"], 1)
            self.assertEqual(Measurement.objects.count(), 1)

        measurement = Measurement.objects.get()
        self.assertEqual(measurement.value, Decimal("91.25"))
        self.assertEqual(
            measurement.breakdown,
            {"itens_publicados": 88, "itens_avaliados": 100},
        )
