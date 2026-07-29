from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from municipal_dashboard.models import Axis, Dimension, Indicator, Measurement


class MunicipalDashboardModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dimension = Dimension.objects.create(
            name="Cidade que Funciona",
            slug="cidade-que-funciona",
            display_order=1,
        )
        cls.axis = Axis.objects.create(
            dimension=cls.dimension,
            name="Eficiência fiscal",
            slug="eficiencia-fiscal",
            display_order=1,
        )
        cls.indicator = Indicator.objects.create(
            axis=cls.axis,
            name="Resultado orçamentário",
            slug="resultado-orcamentario",
            unit="%",
            polarity=Indicator.Polarity.HIGHER_IS_BETTER,
            frequency=Indicator.Frequency.ANNUAL,
            target_value=Decimal("100"),
        )

    def test_dimension_has_configurable_visual_metadata(self):
        self.assertEqual(self.dimension.accent_color, "#1F5E8C")
        self.dimension.accent_color = "azul"
        with self.assertRaises(ValidationError):
            self.dimension.full_clean()

    def test_measurement_natural_key_is_unique(self):
        values = {
            "indicator": self.indicator,
            "period_start": date(2024, 1, 1),
            "period_end": date(2024, 12, 31),
            "value": Decimal("101.5"),
        }
        Measurement.objects.create(**values)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Measurement.objects.create(**values)

    def test_measurement_rejects_inverted_period_and_non_object_breakdown(self):
        measurement = Measurement(
            indicator=self.indicator,
            period_start=date(2024, 12, 31),
            period_end=date(2024, 1, 1),
            value=Decimal("1"),
            breakdown=[],
        )
        with self.assertRaises(ValidationError) as error:
            measurement.full_clean()
        self.assertIn("period_end", error.exception.message_dict)
        self.assertIn("breakdown", error.exception.message_dict)

    def test_period_target_overrides_indicator_target(self):
        measurement = Measurement.objects.create(
            indicator=self.indicator,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 12, 31),
            value=Decimal("102"),
            target_value=Decimal("105"),
        )
        self.assertEqual(measurement.effective_target_value, Decimal("105"))

    def test_hierarchy_uses_explicit_display_order(self):
        first = Axis.objects.create(
            dimension=self.dimension,
            name="Primeiro eixo",
            slug="primeiro-eixo",
            display_order=0,
        )
        self.assertEqual(list(self.dimension.axes.all())[:2], [first, self.axis])
