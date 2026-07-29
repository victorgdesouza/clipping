"""Sincronização idempotente do catálogo e das séries oficiais iniciais.

Os seeds são uma carga de preenchimento inicial: uma medição com a mesma chave
natural nunca é sobrescrita, para preservar correções, revisões e importações
posteriores.
"""

from collections import Counter
from datetime import date
from decimal import Decimal

from django.db import transaction

from .catalog import AXES, DIMENSIONS, INDICATORS
from .models import Axis, Dimension, Indicator, Measurement


OFFICIAL_REPORT_SOURCE = "Conjuntura Econômica 2025 — Prefeitura de São José do Rio Preto"


def _annual_series(indicator_slug, values, *, page, note="", breakdowns=None):
    page_note = f"Fonte: {OFFICIAL_REPORT_SOURCE}, p. {page}."
    if note:
        page_note = f"{page_note} {note}"
    breakdowns = breakdowns or {}
    return tuple(
        {
            "indicator_slug": indicator_slug,
            "year": year,
            "value": str(value),
            "quality": Measurement.Quality.OFFICIAL,
            "source_name": OFFICIAL_REPORT_SOURCE,
            "breakdown": breakdowns.get(year, {}),
            "note": page_note,
        }
        for year, value in values.items()
    )


OFFICIAL_SEEDS = (
    *_annual_series(
        "resultado-fiscal-consolidado-percentual",
        {
            2015: "-2.14",
            2016: "-0.58",
            2017: "4.67",
            2018: "3.64",
            2019: "-1.01",
            2020: "4.76",
            2021: "1.58",
            2022: "4.46",
            2023: "-0.98",
            2024: "4.62",
        },
        page=79,
        note="A metodologia do relatório utiliza receitas e despesas consolidadas.",
    ),
    *_annual_series(
        "gasto-total-saude-por-habitante",
        {
            2020: "996.76",
            2021: "1158.95",
            2022: "1218.98",
            2023: "1394.92",
            2024: "1458.28",
        },
        page=49,
    ),
    *_annual_series(
        "familias-beneficiarias-bolsa-familia",
        {2024: "18741"},
        page=46,
        note="Dado contextual/complementar.",
    ),
    *_annual_series(
        "saldo-empregos-formais",
        {
            2020: "-1946",
            2021: "7683",
            2022: "4727",
            2023: "4309",
            2024: "5691",
        },
        page=72,
        note=(
            "Em 2024, o saldo foi reconciliado por admissões menos desligamentos. "
            "A célula de total setorial impressa repete 4.309 e é inconsistente com os componentes."
        ),
        breakdowns={
            2024: {
                "admissoes": 92355,
                "desligamentos": 86664,
                "saldo_reconciliado": 5691,
                "saldo_total_setorial_impresso": 4309,
                "saldos_setoriais": {
                    "construcao": 484,
                    "industria": 925,
                    "agropecuaria": 20,
                    "comercio": 1540,
                    "servicos": 2722,
                },
            }
        },
    ),
    *_annual_series(
        "solicitacoes-abertura-empresas",
        {2021: "7978", 2022: "19785", 2023: "17311", 2024: "17190"},
        page=70,
    ),
    *_annual_series(
        "solicitacoes-abertura-empresas-deferidas",
        {2021: "4212", 2022: "13815", 2023: "13345", 2024: "14153"},
        page=70,
    ),
    *_annual_series(
        "empresas-ativas",
        {2021: "41558", 2022: "47253", 2023: "50344", 2024: "46235"},
        page=70,
    ),
    *_annual_series(
        "meis-ativos",
        {2021: "31472", 2022: "36022", 2023: "30088", 2024: "26221"},
        page=70,
    ),
    *_annual_series(
        "empresas-parque-tecnologico",
        {2021: "44", 2022: "58", 2023: "59", 2024: "61"},
        page=68,
        note="Total obtido pela soma dos ambientes apresentados no relatório.",
    ),
    *_annual_series(
        "cobertura-abastecimento-agua",
        {2024: "93.93"},
        page=90,
    ),
    *_annual_series(
        "cobertura-coleta-esgoto",
        {2024: "93.93"},
        page=90,
    ),
    *_annual_series(
        "volume-agua-tratada",
        {2024: "141495"},
        page=90,
    ),
    *_annual_series(
        "residuos-domiciliares-coletados",
        {
            2020: "154066.48",
            2021: "146282.64",
            2022: "148875.56",
            2023: "156668.24",
            2024: "158051.16",
        },
        page=91,
    ),
    *_annual_series(
        "extensao-varricao-diurna",
        {
            2020: "59360.67",
            2021: "63496.72",
            2022: "64967.23",
            2023: "64357.87",
            2024: "65541.28",
        },
        page=91,
    ),
    *_annual_series(
        "alunos-educacao-especial-atendidos",
        {2024: "1609"},
        page=45,
        note="Dado contextual; não representa sozinho a taxa de cobertura do AEE.",
    ),
    *_annual_series(
        "total-alunos-rede-municipal",
        {2024: "40277"},
        page=44,
        note="Dado contextual do universo da rede municipal.",
    ),
    *_annual_series(
        "equipamentos-esportivos",
        {2024: "529"},
        page=98,
        note="Dado contextual do estoque de equipamentos.",
    ),
    *_annual_series(
        "exportacoes-valor-usd-fob",
        {
            2018: "15278837",
            2019: "24143756",
            2020: "27208908",
            2021: "28196289",
            2022: "38146022",
            2023: "45049005",
            2024: "51891633",
        },
        page=63,
    ),
)


def _sync_object(model, lookup, values):
    try:
        instance = model.objects.get(**lookup)
    except model.DoesNotExist:
        return model.objects.create(**lookup, **values), "created"

    changed_fields = []
    for field, value in values.items():
        current_value = getattr(instance, field)
        current_comparison = current_value.pk if hasattr(current_value, "pk") else current_value
        value_comparison = value.pk if hasattr(value, "pk") else value
        if current_comparison != value_comparison:
            setattr(instance, field, value)
            changed_fields.append(field)
    if changed_fields:
        instance.save(update_fields=[*changed_fields, "updated_at"])
        return instance, "updated"
    return instance, "unchanged"


def _empty_summary():
    return {"created": 0, "updated": 0, "unchanged": 0}


def _sync_catalog_objects():
    summary = {
        "dimensions": _empty_summary(),
        "axes": _empty_summary(),
        "indicators": _empty_summary(),
    }
    dimensions_by_slug = {}
    for definition in DIMENSIONS:
        values = {
            "name": definition["name"],
            "description": definition["description"],
            "accent_color": definition["accent_color"],
            "icon_name": definition["icon_name"],
            "display_order": definition["display_order"],
            "is_active": True,
        }
        dimension, action = _sync_object(
            Dimension,
            {"slug": definition["slug"]},
            values,
        )
        dimensions_by_slug[definition["slug"]] = dimension
        summary["dimensions"][action] += 1

    axes_by_number = {}
    for definition in AXES:
        values = {
            "dimension": dimensions_by_slug[definition["dimension_slug"]],
            "name": definition["name"],
            "description": definition["description"],
            "display_order": definition["number"],
            "is_active": True,
        }
        axis, action = _sync_object(Axis, {"slug": definition["slug"]}, values)
        axes_by_number[definition["number"]] = axis
        summary["axes"][action] += 1

    indicator_orders = Counter()
    for definition in INDICATORS:
        axis_number = definition["axis_number"]
        indicator_orders[axis_number] += 1
        values = {
            "axis": axes_by_number[axis_number],
            "name": definition["name"],
            "description": definition["description"],
            "methodology": definition["methodology"],
            "unit": definition["unit"],
            "kind": definition["kind"],
            "polarity": definition["polarity"],
            "frequency": definition["frequency"],
            "source_name": definition["source_name"],
            "source_url": "",
            "display_order": indicator_orders[axis_number],
            "is_active": True,
        }
        _, action = _sync_object(Indicator, {"slug": definition["slug"]}, values)
        summary["indicators"][action] += 1

    return summary


def _sync_official_seeds():
    summary = _empty_summary()
    indicator_slugs = {seed["indicator_slug"] for seed in OFFICIAL_SEEDS}
    indicators = {
        indicator.slug: indicator
        for indicator in Indicator.objects.filter(slug__in=indicator_slugs)
    }
    missing = sorted(indicator_slugs - set(indicators))
    if missing:
        raise RuntimeError(
            "Indicadores necessários aos seeds não foram sincronizados: "
            + ", ".join(missing)
        )

    for seed in OFFICIAL_SEEDS:
        year = seed["year"]
        lookup = {
            "indicator": indicators[seed["indicator_slug"]],
            "period_start": date(year, 1, 1),
            "period_end": date(year, 12, 31),
        }
        defaults = {
            "value": Decimal(seed["value"]),
            "quality": seed["quality"],
            "source_name": seed["source_name"],
            "source_url": "",
            "breakdown": seed["breakdown"],
            "note": seed["note"],
        }
        _, created = Measurement.objects.get_or_create(**lookup, defaults=defaults)
        summary["created" if created else "unchanged"] += 1
    return summary


@transaction.atomic
def sync_catalog(*, include_seeds=True):
    """Sincroniza catálogo e séries oficiais sem duplicar registros.

    Metas de indicadores e de medições não são alteradas. Registros fora do
    catálogo também não são apagados ou desativados automaticamente. Os seeds
    usam somente ``get_or_create``: qualquer medição preexistente é preservada,
    mesmo quando seu valor ou sua qualidade difere da carga inicial.
    """

    summary = _sync_catalog_objects()
    summary["measurements"] = (
        _sync_official_seeds() if include_seeds else _empty_summary()
    )
    return summary
