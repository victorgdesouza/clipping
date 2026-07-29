import json
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from municipal_dashboard.models import Axis, Dimension, Indicator, Measurement


class MunicipalDashboardReadApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dimension = Dimension.objects.create(
            name="Cidade que Funciona",
            slug="cidade-que-funciona",
            accent_color="#245A75",
            icon_name="building",
            display_order=1,
        )
        cls.axis = Axis.objects.create(
            dimension=cls.dimension,
            name="Eficiência fiscal e orçamentária",
            slug="eficiencia-fiscal",
            display_order=1,
        )
        cls.indicator = Indicator.objects.create(
            axis=cls.axis,
            name="Receita realizada",
            slug="receita-realizada",
            unit="%",
            polarity=Indicator.Polarity.HIGHER_IS_BETTER,
            frequency=Indicator.Frequency.ANNUAL,
            target_value=Decimal("100"),
            source_name="Portal da Transparência",
        )
        cls.indicator_without_data = Indicator.objects.create(
            axis=cls.axis,
            name="Despesa liquidada",
            slug="despesa-liquidada",
            unit="R$",
            display_order=2,
        )
        cls.measurement_2023 = Measurement.objects.create(
            indicator=cls.indicator,
            period_start=date(2023, 1, 1),
            period_end=date(2023, 12, 31),
            value=Decimal("90"),
            quality=Measurement.Quality.OFFICIAL,
        )
        cls.measurement_2024 = Measurement.objects.create(
            indicator=cls.indicator,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 12, 31),
            value=Decimal("110"),
            quality=Measurement.Quality.VERIFIED,
            breakdown={"região": {"norte": 52, "sul": 58}},
        )

    def test_overview_returns_taxonomy_measurements_status_and_coverage(self):
        response = self.client.get(reverse("municipal_dashboard:api_overview"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["years"], [2024, 2023])
        self.assertEqual(payload["dimensions"][0]["accent_color"], "#245A75")
        self.assertEqual(payload["dimensions"][0]["icon_name"], "building")
        self.assertEqual(payload["counts"]["indicators"], 2)
        self.assertEqual(payload["counts"]["indicators_with_data"], 1)
        self.assertEqual(payload["coverage"]["percentage"], 50.0)
        revenue = next(item for item in payload["indicators"] if item["slug"] == "receita-realizada")
        self.assertEqual(revenue["current_measurement"]["value"], 110.0)
        self.assertEqual(revenue["previous_measurement"]["value"], 90.0)
        self.assertEqual(revenue["status"]["code"], "target_met")

    def test_overview_filters_by_year_dimension_axis_and_query(self):
        response = self.client.get(
            reverse("municipal_dashboard:api_overview"),
            {
                "year": 2023,
                "dimension": self.dimension.slug,
                "axis": str(self.axis.pk),
                "q": "receita",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["counts"]["indicators"], 1)
        self.assertEqual(payload["indicators"][0]["current_measurement"]["value"], 90.0)
        self.assertEqual(payload["indicators"][0]["status"]["code"], "target_not_met")

    def test_overview_rejects_invalid_year(self):
        response = self.client.get(
            reverse("municipal_dashboard:api_overview"),
            {"year": "ontem"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_indicator_detail_returns_chronological_series(self):
        response = self.client.get(
            reverse(
                "municipal_dashboard:api_indicator_detail",
                kwargs={"slug": self.indicator.slug},
            )
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 2)
        self.assertEqual(
            [item["year"] for item in payload["measurements"]],
            [2023, 2024],
        )
        self.assertEqual(
            payload["measurements"][-1]["breakdown"],
            {"região": {"norte": 52, "sul": 58}},
        )

    def test_indicator_detail_returns_json_for_unknown_indicator(self):
        response = self.client.get(
            reverse(
                "municipal_dashboard:api_indicator_detail",
                kwargs={"slug": "indicador-inexistente"},
            )
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"error": "Indicador não encontrado."})

    def test_freshness_reports_indicators_with_and_without_data(self):
        response = self.client.get(reverse("municipal_dashboard:api_freshness"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["counts"]["indicators"], 2)
        self.assertEqual(payload["counts"]["fresh"], 1)
        self.assertEqual(payload["counts"]["no_data"], 1)


class MunicipalDashboardWriteApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        dimension = Dimension.objects.create(name="Gestão", slug="gestao")
        axis = Axis.objects.create(dimension=dimension, name="Finanças", slug="financas")
        cls.indicator = Indicator.objects.create(
            axis=axis,
            name="Índice fiscal",
            slug="indice-fiscal",
            unit="%",
        )
        user_model = get_user_model()
        cls.staff = user_model.objects.create_user(
            username="staff-indicadores",
            password="senha-segura",
            is_staff=True,
        )
        cls.regular_user = user_model.objects.create_user(
            username="leitor-indicadores",
            password="senha-segura",
        )

    def measurement_payload(self, value="98.5"):
        return {
            "indicator_slug": self.indicator.slug,
            "period_start": "2024-01-01",
            "period_end": "2024-12-31",
            "value": value,
            "quality": "official",
            "source_name": "Secretaria Municipal",
            "breakdown": {"zona": {"urbana": 80, "rural": 18.5}},
        }

    def test_measurement_endpoint_requires_authentication_and_staff(self):
        url = reverse("municipal_dashboard:api_measurements")
        response = self.client.post(
            url,
            data=json.dumps(self.measurement_payload()),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

        self.client.force_login(self.regular_user)
        response = self.client.post(
            url,
            data=json.dumps(self.measurement_payload()),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_upsert_is_idempotent_for_indicator_and_period(self):
        self.client.force_login(self.staff)
        url = reverse("municipal_dashboard:api_measurements")
        body = json.dumps(self.measurement_payload())

        first = self.client.post(url, data=body, content_type="application/json")
        second = self.client.post(url, data=body, content_type="application/json")

        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json()["created"], 1)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["unchanged"], 1)
        self.assertEqual(Measurement.objects.count(), 1)

    def test_upsert_updates_value_without_creating_duplicate(self):
        self.client.force_login(self.staff)
        url = reverse("municipal_dashboard:api_measurements")
        self.client.post(
            url,
            data=json.dumps(self.measurement_payload("98.5")),
            content_type="application/json",
        )
        response = self.client.post(
            url,
            data=json.dumps(self.measurement_payload("101.25")),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["updated"], 1)
        self.assertEqual(Measurement.objects.count(), 1)
        self.assertEqual(Measurement.objects.get().value, Decimal("101.25"))

    def test_write_endpoint_keeps_csrf_protection(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.staff)
        url = reverse("municipal_dashboard:api_measurements")
        body = json.dumps(self.measurement_payload())

        rejected = csrf_client.post(url, data=body, content_type="application/json")
        self.assertEqual(rejected.status_code, 403)

        csrf_client.get(reverse("municipal_dashboard:dashboard"))
        token = csrf_client.cookies["csrftoken"].value
        accepted = csrf_client.post(
            url,
            data=body,
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(accepted.status_code, 201)

    def test_invalid_breakdown_rolls_back_request(self):
        self.client.force_login(self.staff)
        payload = self.measurement_payload()
        payload["breakdown"] = ["não", "é", "objeto"]
        response = self.client.post(
            reverse("municipal_dashboard:api_measurements"),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["field"], "breakdown")
        self.assertFalse(Measurement.objects.exists())
