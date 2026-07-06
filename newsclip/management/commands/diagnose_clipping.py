from datetime import date

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Q

from newsclip.models import Article, Client, DiscoveryRun, FetchLog, RelevanceAuditLog, Source


class Command(BaseCommand):
    help = "Diagnostica cobertura, relevancia e fontes para um cliente."

    def add_arguments(self, parser):
        parser.add_argument("--client", default="Fabio Candido", help="Trecho do nome do cliente")
        parser.add_argument("--start", default="2026-04-01", help="Data inicial YYYY-MM-DD")
        parser.add_argument("--end", default="2026-07-06", help="Data final YYYY-MM-DD")

    def handle(self, *args, **options):
        start = date.fromisoformat(options["start"])
        end = date.fromisoformat(options["end"])
        client = Client.objects.filter(name__icontains=options["client"]).first()
        if not client:
            raise CommandError(f"Cliente nao encontrado: {options['client']}")

        self.stdout.write(f"=== Diagnostico: {client.name} ({start} a {end}) ===")
        self.stdout.write("")

        self.stdout.write("=== Variaveis criticas ===")
        for name in [
            "BRAVE_SEARCH_API_KEY",
            "NEWSAPI_API_KEY",
            "NEWSDATA_API_KEY",
            "GOOGLE_API_KEY",
            "GOOGLE_CSE_ID",
            "YOUTUBE_API_KEY",
        ]:
            value = getattr(settings, name, "")
            self.stdout.write(f"{name}: {'OK' if value else 'AUSENTE'}")

        self.stdout.write("")
        self.stdout.write("=== Rodadas de descoberta ===")
        runs = DiscoveryRun.objects.filter(
            client=client,
            started_at__date__gte=start,
            started_at__date__lte=end,
        ).order_by("started_at")
        if not runs.exists():
            self.stdout.write("Nenhuma rodada de descoberta registrada.")
        for run in runs:
            self.stdout.write(
                f"{run.started_at:%d/%m %H:%M} {run.provider} {run.status} "
                f"queries:{run.queries_count} resultados:{run.results_count} "
                f"relevantes:{run.relevant_count} artigos:{run.articles_count} "
                f"erro:{(run.error_message or '')[:120]}"
            )

        self.stdout.write("")
        self.stdout.write("=== Erros e avisos no FetchLog ===")
        logs = FetchLog.objects.filter(
            client=client,
            level__in=["ERROR", "WARNING"],
            created_at__date__gte=start,
            created_at__date__lte=end,
        ).order_by("created_at")
        if not logs.exists():
            self.stdout.write("Nenhum erro/aviso no periodo.")
        for log in logs[:200]:
            self.stdout.write(f"{log.created_at:%d/%m %H:%M} {log.level} {log.message[:180]}")

        self.stdout.write("")
        self.stdout.write("=== Fontes criticas e endpoints ===")
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
            self.stdout.write("Nenhuma fonte critica localizada.")
        for src in sources:
            self.stdout.write(f"{src.name} | {src.domain} | status:{src.status} | ativa:{src.is_active}")
            for ep in src.endpoints.all().order_by("endpoint_type", "url"):
                self.stdout.write(
                    f"  endpoint:{ep.endpoint_type} ativo:{ep.is_active} erros:{ep.consecutive_errors} "
                    f"ultimo_sucesso:{ep.last_success_at} ultimo_erro:{ep.last_error_at} url:{ep.url[:140]}"
                )

        self.stdout.write("")
        self.stdout.write("=== Decisoes de relevancia ===")
        audits = RelevanceAuditLog.objects.filter(client=client, created_at__date__gte=start, created_at__date__lte=end)
        audit_counts = audits.values("decision").annotate(total=Count("id")).order_by("decision")
        if not audit_counts:
            self.stdout.write("Nenhuma decisao auditada no periodo.")
        for item in audit_counts:
            self.stdout.write(f"{item['decision']}: {item['total']}")

        self.stdout.write("")
        self.stdout.write("=== Artigos salvos por status ===")
        articles = Article.objects.filter(client=client, created_at__date__gte=start, created_at__date__lte=end)
        status_counts = articles.values("validation_status").annotate(total=Count("id")).order_by("validation_status")
        if not status_counts:
            self.stdout.write("Nenhum artigo salvo no periodo.")
        for item in status_counts:
            self.stdout.write(f"{item['validation_status']}: {item['total']}")

        review = articles.filter(validation_status="REVIEW", excluded=False).order_by("-created_at")[:20]
        if review:
            self.stdout.write("")
            self.stdout.write("=== Ultimas noticias presas em REVIEW ===")
            for article in review:
                self.stdout.write(
                    f"{article.created_at:%d/%m %H:%M} score:{article.relevance_score} "
                    f"{article.source} | {article.title[:180]} | motivo:{article.validation_reason[:120]}"
                )

        accepted_recent = Article.objects.filter(
            client=client,
            excluded=False,
            validation_status="ACCEPTED",
            published_at__date__gte=start,
            published_at__date__lte=end,
        ).order_by("-published_at")[:30]
        self.stdout.write("")
        self.stdout.write("=== Ultimas noticias aceitas no periodo ===")
        for article in accepted_recent:
            self.stdout.write(f"{article.published_at:%d/%m %H:%M} {article.source} | {article.title[:180]}")
