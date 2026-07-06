from datetime import date

from django.conf import settings
from django.db.models import Count, Q

from newsclip.models import Article, Client, DiscoveryRun, FetchLog, RelevanceAuditLog, Source


def _line(lines: list[str], value: str = "") -> None:
    lines.append(value)


def build_clipping_diagnostic(client_query: str = "Fabio Candido", start=None, end=None) -> tuple[Client | None, str]:
    """Gera um diagnóstico textual sem expor valores de chaves/segredos."""
    start = start or date(2026, 4, 1)
    end = end or date.today()
    client = Client.objects.filter(name__icontains=client_query).first()
    lines: list[str] = []

    if not client:
        return None, f"Cliente nao encontrado: {client_query}"

    _line(lines, f"=== Diagnostico: {client.name} ({start} a {end}) ===")
    _line(lines)

    _line(lines, "=== Variaveis criticas ===")
    for name in [
        "BRAVE_SEARCH_API_KEY",
        "NEWSAPI_API_KEY",
        "NEWSDATA_API_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_CSE_ID",
        "YOUTUBE_API_KEY",
    ]:
        value = getattr(settings, name, "")
        _line(lines, f"{name}: {'OK' if value else 'AUSENTE'}")

    _line(lines)
    _line(lines, "=== Rodadas de descoberta ===")
    runs = DiscoveryRun.objects.filter(
        client=client,
        started_at__date__gte=start,
        started_at__date__lte=end,
    ).order_by("started_at")
    if not runs.exists():
        _line(lines, "Nenhuma rodada de descoberta registrada.")
    for run in runs:
        _line(
            lines,
            f"{run.started_at:%d/%m %H:%M} {run.provider} {run.status} "
            f"queries:{run.queries_count} resultados:{run.results_count} "
            f"relevantes:{run.relevant_count} artigos:{run.articles_count} "
            f"erro:{(run.error_message or '')[:120]}",
        )

    _line(lines)
    _line(lines, "=== Erros e avisos no FetchLog ===")
    logs = FetchLog.objects.filter(
        client=client,
        level__in=["ERROR", "WARNING"],
        created_at__date__gte=start,
        created_at__date__lte=end,
    ).order_by("created_at")
    if not logs.exists():
        _line(lines, "Nenhum erro/aviso no periodo.")
    for log in logs[:200]:
        _line(lines, f"{log.created_at:%d/%m %H:%M} {log.level} {log.message[:180]}")

    _line(lines)
    _line(lines, "=== Fontes criticas e endpoints ===")
    critical_terms = [
        "g1",
        "dlnews",
        "regiaonoroeste",
        "região noroeste",
        "diario",
        "diário",
        "diariodaregiao",
        "gazeta",
        "band",
        "record",
        "ncnews",
    ]
    source_filter = Q()
    for term in critical_terms:
        source_filter |= Q(name__icontains=term) | Q(domain__icontains=term) | Q(url__icontains=term)
    sources = Source.objects.filter(source_filter).prefetch_related("endpoints").order_by("name").distinct()
    if not sources.exists():
        _line(lines, "Nenhuma fonte critica localizada.")
    for src in sources:
        _line(lines, f"{src.name} | {src.domain} | status:{src.status} | ativa:{src.is_active}")
        for ep in src.endpoints.all().order_by("endpoint_type", "url"):
            _line(
                lines,
                f"  endpoint:{ep.endpoint_type} ativo:{ep.is_active} erros:{ep.consecutive_errors} "
                f"ultimo_sucesso:{ep.last_success_at} ultimo_erro:{ep.last_error_at} url:{ep.url[:140]}",
            )

    _line(lines)
    _line(lines, "=== Decisoes de relevancia ===")
    audits = RelevanceAuditLog.objects.filter(client=client, created_at__date__gte=start, created_at__date__lte=end)
    audit_counts = audits.values("decision").annotate(total=Count("id")).order_by("decision")
    if not audit_counts:
        _line(lines, "Nenhuma decisao auditada no periodo.")
    for item in audit_counts:
        _line(lines, f"{item['decision']}: {item['total']}")

    _line(lines)
    _line(lines, "=== Artigos salvos por status ===")
    articles = Article.objects.filter(client=client, created_at__date__gte=start, created_at__date__lte=end)
    status_counts = articles.values("validation_status").annotate(total=Count("id")).order_by("validation_status")
    if not status_counts:
        _line(lines, "Nenhum artigo salvo no periodo.")
    for item in status_counts:
        _line(lines, f"{item['validation_status']}: {item['total']}")

    review = articles.filter(validation_status="REVIEW", excluded=False).order_by("-created_at")[:20]
    if review:
        _line(lines)
        _line(lines, "=== Ultimas noticias presas em REVIEW ===")
        for article in review:
            _line(
                lines,
                f"{article.created_at:%d/%m %H:%M} score:{article.relevance_score} "
                f"{article.source} | {article.title[:180]} | motivo:{article.validation_reason[:120]}",
            )

    accepted_recent = Article.objects.filter(
        client=client,
        excluded=False,
        validation_status="ACCEPTED",
        published_at__date__gte=start,
        published_at__date__lte=end,
    ).order_by("-published_at")[:30]
    _line(lines)
    _line(lines, "=== Ultimas noticias aceitas no periodo ===")
    if not accepted_recent:
        _line(lines, "Nenhuma noticia aceita no periodo.")
    for article in accepted_recent:
        _line(lines, f"{article.published_at:%d/%m %H:%M} {article.source} | {article.title[:180]}")

    return client, "\n".join(lines)
