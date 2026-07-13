import json
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.core.management import call_command
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import connection
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, ListView, UpdateView
from django_q.tasks import async_task

from .diagnostics import build_clipping_diagnostic
from .learning import record_manual_feedback
from .forms import ClientForm, ReportForm
from .models import Article, Client, DiscoveryRun, GeneratedReport, NewsFetchJob, Source, TranscriptExtraction
from .transcripts import export_files, extract_video_id, zip_files
from .utils import (
    append_unique_terms,
    deduplicate_articles_for_display,
    is_trusted_source,
    normalize_match_text,
    revalidate_accepted_articles_for_client,
    revalidate_pending_articles_for_client,
    split_terms,
    strong_client_identity_terms,
)


SUGGESTED_PUBLIC_ROLE_VARIATIONS = (
    "Prefeito de Rio Preto, Prefeito de São José do Rio Preto, "
    "Prefeito Fábio Candido, Prefeito Coronel Fábio Candido"
)


def _admin_only(request):
    return request.user.is_superuser


@login_required
def youtube_transcript_extractor(request):
    if not _admin_only(request):
        return HttpResponseForbidden("Este recurso é exclusivo do administrador.")
    return render(request, "newsclip/youtube_transcript.html")


@require_POST
@login_required
def youtube_transcript_start(request):
    if not _admin_only(request):
        return HttpResponseForbidden("Este recurso é exclusivo do administrador.")
    url = request.POST.get("url", "").strip()
    try:
        extract_video_id(url)
    except ValueError as error:
        return JsonResponse({"error": str(error)}, status=400)
    active = TranscriptExtraction.objects.filter(status__in=["queued", "running"]).order_by("-created_at").first()
    if active:
        return JsonResponse({"error": "Já existe uma extração em andamento."}, status=409)
    job = TranscriptExtraction.objects.create(created_by=request.user, video_url=url)
    try:
        task_id = async_task("newsclip.tasks.extract_youtube_transcript_task", job.pk, task_name=f"youtube-transcript-{job.pk}")
    except Exception:
        job.status = "failed"
        job.error_message = "Não foi possível iniciar a extração. Tente novamente."
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
        return JsonResponse({"error": job.error_message}, status=503)
    job.task_id = str(task_id)
    job.save(update_fields=["task_id", "updated_at"])
    return JsonResponse({"status": "queued", "status_url": reverse("youtube_transcript_status", args=[job.pk])}, status=202)


@login_required
def youtube_transcript_status(request, job_id):
    if not _admin_only(request):
        return HttpResponseForbidden("Este recurso é exclusivo do administrador.")
    job = get_object_or_404(TranscriptExtraction, pk=job_id)
    if job.status in {"queued", "running"} and job.created_at < timezone.now() - timedelta(minutes=15):
        job.status, job.error_message, job.finished_at = "failed", "Tempo limite excedido ao buscar a transcrição.", timezone.now()
        job.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
    payload = {"status": job.status, "message": job.error_message or ("Transcrição concluída." if job.status == "completed" else "Processando transcrição..."), "title": job.title, "channel": job.channel, "language": job.language, "source": job.source, "segment_count": len(job.segments), "download_base": reverse("youtube_transcript_download", args=[job.pk, "txt"]).removesuffix("txt/")}
    return JsonResponse(payload)


@login_required
def youtube_transcript_download(request, job_id, file_type):
    if not _admin_only(request):
        return HttpResponseForbidden("Este recurso é exclusivo do administrador.")
    job = get_object_or_404(TranscriptExtraction, pk=job_id, status="completed")
    base = f"transcricao_{job.video_id}"
    if file_type == "zip":
        response = HttpResponse(zip_files(job), content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="{base}.zip"'
        return response
    files = export_files(job)
    expected = f"{base}.{file_type}"
    if file_type not in {"txt", "json", "srt"} or expected not in files:
        return HttpResponse("Arquivo indisponível.", status=404)
    content_type = {"txt": "text/plain; charset=utf-8", "json": "application/json", "srt": "application/x-subrip; charset=utf-8"}[file_type]
    response = HttpResponse(files[expected], content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{expected}"'
    return response

TRIAGE_PRIORITY_SOURCES = (
    "G1",
    "Diário da Região",
    "Gazeta de Rio Preto",
    "Região Noroeste",
    "Band Paulista",
    "Record Rio Preto",
    "Prefeitura de Rio Preto",
)
TRIAGE_GROUP_STOP_WORDS = {
    "a", "as", "com", "da", "das", "de", "do", "dos", "e", "em", "na", "nas",
    "no", "nos", "o", "os", "para", "por", "que", "um", "uma",
}


def _review_score_band(score):
    score = int(score or 0)
    if 60 <= score <= 69:
        return 0
    if score >= 70:
        return 1
    if 50 <= score <= 59:
        return 2
    return 3


def sort_review_articles_by_priority(articles, client):
    identity_terms = [
        normalize_match_text(term)
        for term in strong_client_identity_terms(client)
        if normalize_match_text(term)
    ]
    source_ranks = {
        normalize_match_text(source): rank
        for rank, source in enumerate(TRIAGE_PRIORITY_SOURCES)
    }

    def priority_key(article):
        score = int(article.relevance_score or 0)
        visible_text = normalize_match_text(f"{article.title} {article.url} {article.source}")
        identity_visible = any(term in visible_text for term in identity_terms)
        trusted = is_trusted_source(client, article.url, article.source)
        source_rank = source_ranks.get(normalize_match_text(article.source), len(source_ranks) + 1)
        title_words = [
            word
            for word in normalize_match_text(article.title).split()
            if word not in TRIAGE_GROUP_STOP_WORDS
        ]
        story_group = " ".join(title_words[:4])
        published = article.published_at or article.created_at
        published_timestamp = published.timestamp() if published else 0
        return (
            _review_score_band(score),
            0 if trusted else 1,
            source_rank,
            0 if identity_visible else 1,
            -score,
            story_group,
            -published_timestamp,
            -article.pk,
        )

    return sorted(articles, key=priority_key)


def suggested_role_variations_for_client(client):
    if not client:
        return ""
    normalized_name = normalize_match_text(client.name)
    if "fabio" in normalized_name and "candido" in normalized_name:
        return SUGGESTED_PUBLIC_ROLE_VARIATIONS
    return ""


def user_can_access_client(user, client):
    if user.is_superuser:
        return True
    if hasattr(client, "users") and callable(getattr(client.users, "all", None)):
        return user in client.users.all()
    return False


def clients_for_user(user):
    if user.is_superuser:
        return Client.objects.all()
    if hasattr(user, "clients"):
        return user.clients.all()
    return Client.objects.none()


def apply_article_search(queryset, search_text):
    if not search_text:
        return queryset

    if connection.vendor == "postgresql":
        query_fts = SearchQuery(search_text, search_type="websearch", config="portuguese")
        return queryset.annotate(
            search_rank=SearchRank("search_vector", query_fts),
        ).filter(search_vector=query_fts).order_by("-search_rank", "-published_at")

    return queryset.filter(
        Q(title__icontains=search_text)
        | Q(summary__icontains=search_text)
        | Q(content__icontains=search_text)
        | Q(source__icontains=search_text)
    )


class SignUpView(CreateView):
    template_name = "registration/signup.html"
    form_class = UserCreationForm
    success_url = reverse_lazy("dashboard")

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(self.request, "Conta criada com sucesso.")
        return response


class ClientCreateView(LoginRequiredMixin, CreateView):
    model = Client
    form_class = ClientForm
    template_name = "newsclip/client_form.html"

    def get_success_url(self):
        return reverse("dashboard")

    def form_valid(self, form):
        response = super().form_valid(form)
        if hasattr(self.object, "users") and callable(getattr(self.object.users, "add", None)):
            self.object.users.add(self.request.user)
        return response


class ClientUpdateView(LoginRequiredMixin, UpdateView):
    model = Client
    form_class = ClientForm
    template_name = "newsclip/client_form.html"

    def get_queryset(self):
        return clients_for_user(self.request.user)

    def get_success_url(self):
        return reverse("dashboard")

    def form_valid(self, form):
        response = super().form_valid(form)
        if hasattr(self.object, "users") and callable(getattr(self.object.users, "add", None)):
            self.object.users.add(self.request.user)
        if self.request.POST.get("save_and_reprocess") == "1":
            stats = revalidate_pending_articles_for_client(self.object, statuses=["REVIEW", "REJECTED"])
            messages.success(
                self.request,
                "Cliente salvo e pendentes reprocessadas: "
                f"{stats['processed']} processadas, {stats['promoted']} promovidas para validadas, "
                f"{stats['changed']} alteradas.",
            )
        else:
            messages.success(self.request, "Cliente salvo com sucesso.")
        return response


class ClientDeleteView(LoginRequiredMixin, DeleteView):
    model = Client
    template_name = "newsclip/client_confirm_delete.html"
    success_url = reverse_lazy("dashboard")

    def get_queryset(self):
        return clients_for_user(self.request.user)


class BuscarTodasNoticiasView(LoginRequiredMixin, ListView):
    template_name = "newsclip/todas_noticias.html"
    context_object_name = "clientes_data"

    def get_queryset(self):
        return clients_for_user(self.request.user).order_by("name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        clientes_noticias_display = []

        for cliente in context[self.context_object_name]:
            artigos_unicos = deduplicate_articles_for_display(
                Article.objects.filter(client=cliente, excluded=False, validation_status="ACCEPTED").order_by("-published_at", "-id")
            )
            clientes_noticias_display.append(
                {
                    "cliente": cliente,
                    "noticias": artigos_unicos[:5],
                    "total": len(artigos_unicos),
                }
            )

        context["clientes_noticias_display"] = clientes_noticias_display
        return context


def noticias_cliente_json(request, pk):
    client = get_object_or_404(Client, pk=pk)
    if not request.user.is_authenticated or not user_can_access_client(request.user, client):
        return HttpResponseForbidden()

    revalidate_accepted_articles_for_client(client, limit=100)
    artigos = deduplicate_articles_for_display(
        Article.objects.filter(client=client, excluded=False, validation_status="ACCEPTED").order_by("-published_at", "-id")
    )
    dados = [
        {
            "id": artigo.id,
            "title": artigo.title,
            "source": artigo.source,
            "published_at": artigo.published_at.strftime("%d/%m/%Y %H:%M") if artigo.published_at else "N/A",
            "url": artigo.url,
            "excluded": artigo.excluded,
        }
        for artigo in artigos
    ]
    return JsonResponse({"noticias": dados})


@login_required
def dashboard(request):
    clients = list(clients_for_user(request.user).order_by("name"))
    since = timezone.now() - timedelta(days=30)
    total_articles = 0
    total_sources = set()
    active_providers = set()

    for client in clients:
        articles = Article.objects.filter(client=client, excluded=False, validation_status="ACCEPTED")
        metrics = articles.aggregate(
            total=Count("id"),
            recent=Count("id", filter=Q(published_at__gte=since) | Q(created_at__gte=since)),
            sources=Count("source", distinct=True),
            providers=Count("provider", distinct=True),
            accepted=Count("id", filter=Q(validation_status="ACCEPTED")),
            review=Count("id", filter=Q(validation_status="REVIEW")),
        )
        providers = sorted(set(articles.exclude(provider="").values_list("provider", flat=True)))
        latest_run = DiscoveryRun.objects.filter(client=client).order_by("-started_at").first()
        accepted_rate = round((metrics["accepted"] / metrics["total"] * 100), 0) if metrics["total"] else 0
        coverage_score = min(
            100,
            min(metrics["recent"], 20) * 2
            + min(metrics["sources"], 5) * 8
            + min(metrics["providers"], 6) * 5
            + round(accepted_rate * 0.2),
        )
        client.coverage = {
            **metrics,
            "accepted_rate": int(accepted_rate),
            "score": int(coverage_score),
            "providers_list": providers,
            "latest_run": latest_run,
        }
        total_articles += metrics["total"]
        total_sources.update(articles.exclude(source="").values_list("source", flat=True))
        active_providers.update(providers)

    return render(
        request,
        "newsclip/dashboard.html",
        {
            "clients": clients,
            "coverage_summary": {
                "articles": total_articles,
                "sources": len(total_sources),
                "providers": len(active_providers),
                "clients": len(clients),
            },
        },
    )


@login_required
def monitored_sources(request):
    if request.method == "POST":
        if not request.user.is_superuser:
            return HttpResponseForbidden("Apenas superusuarios podem manter fontes.")
        action = request.POST.get("action")
        source = get_object_or_404(Source, pk=request.POST.get("source_id"))
        if action == "activate":
            source.is_active = True
            source.status = "ACTIVE"
            source.save(update_fields=["is_active", "status"])
            source.endpoints.update(is_active=True, consecutive_errors=0)
            messages.success(request, f"Fonte ativada: {source.name}")
        elif action == "verify":
            source.status = "VERIFIED"
            source.save(update_fields=["status"])
            source.endpoints.update(consecutive_errors=0)
            messages.success(request, f"Fonte marcada como verificada: {source.name}")
        elif action == "deactivate":
            source.is_active = False
            source.status = "DEGRADED"
            source.save(update_fields=["is_active", "status"])
            source.endpoints.update(is_active=False)
            messages.success(request, f"Fonte desativada das buscas: {source.name}")
        elif action == "reset_errors":
            source.endpoints.update(consecutive_errors=0, is_active=True)
            if source.status == "DEGRADED":
                source.status = "ACTIVE" if source.is_active else "VERIFIED"
                source.save(update_fields=["status"])
            messages.success(request, f"Falhas limpas para: {source.name}")
        else:
            messages.error(request, "Acao de fonte invalida.")
        redirect_url = reverse("monitored_sources")
        query_string = request.POST.get("return_query") or ""
        return redirect(f"{redirect_url}?{query_string}" if query_string else redirect_url)

    status_filter = request.GET.get("status", "")
    query = (request.GET.get("q") or "").strip()

    sources = (
        Source.objects.filter(
            Q(is_active=True)
            | Q(status__in=["ACTIVE", "VERIFIED", "DEGRADED"])
            | Q(endpoints__consecutive_errors__gte=1)
        )
        .prefetch_related("endpoints")
        .order_by("-is_active", "-last_discovered_at", "name")
        .distinct()
    )

    if status_filter == "active":
        sources = sources.filter(is_active=True)
    elif status_filter == "verified":
        sources = sources.filter(is_active=False, status="VERIFIED")
    elif status_filter == "degraded":
        sources = sources.filter(Q(status="DEGRADED") | Q(endpoints__consecutive_errors__gte=3)).distinct()
    elif status_filter == "problematic":
        sources = sources.filter(Q(status="DEGRADED") | Q(endpoints__consecutive_errors__gte=1) | Q(is_active=False)).distinct()
    elif status_filter == "inactive":
        sources = sources.filter(is_active=False)

    if query:
        sources = sources.filter(
            Q(name__icontains=query)
            | Q(domain__icontains=query)
            | Q(url__icontains=query)
        )

    source_items = []
    for source in sources[:300]:
        endpoints = list(source.endpoints.all().order_by("-consecutive_errors", "endpoint_type", "url"))
        has_problem = source.status == "DEGRADED" or (not source.is_active) or any(
            endpoint.consecutive_errors for endpoint in endpoints
        )
        source_items.append(
            {
                "source": source,
                "status_label": (
                    "Com falhas"
                    if source.status == "DEGRADED"
                    else ("Ativa nas buscas" if source.is_active else "Verificada")
                ),
                "status_class": (
                    "quality-review"
                    if source.status == "DEGRADED"
                    else ("quality-accepted" if source.is_active else "quality-review")
                ),
                "endpoints": endpoints,
                "has_problem": has_problem,
            }
        )

    return render(
        request,
        "newsclip/monitored_sources.html",
        {
            "source_items": source_items,
            "status_filter": status_filter,
            "query": query,
            "total_sources": len(source_items),
            "is_superuser": request.user.is_superuser,
            "return_query": request.GET.urlencode(),
        },
    )


@login_required
def clipping_diagnostic(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Apenas superusuarios podem acessar o diagnostico.")

    if request.method == "POST":
        action = request.POST.get("action")
        post_client_id = (request.POST.get("client_id") or "").strip()
        if action == "revalidate_pending" and post_client_id.isdigit():
            client_obj = Client.objects.filter(pk=int(post_client_id)).first()
            if client_obj is None:
                messages.error(request, "Cliente nao encontrado para revalidacao.")
            else:
                variation_terms = split_terms(request.POST.get("name_variations_to_add") or "")
                updated_value, added_terms = append_unique_terms(client_obj.name_variations, variation_terms)
                if added_terms:
                    client_obj.name_variations = updated_value
                    client_obj.save(update_fields=["name_variations"])
                stats = revalidate_pending_articles_for_client(client_obj, statuses=["REVIEW", "REJECTED"])
                messages.success(
                    request,
                    "Revalidacao concluida: "
                    f"{stats['processed']} processadas, {stats['promoted']} promovidas para validadas, "
                    f"{stats['changed']} alteradas. "
                    f"Variacoes adicionadas: {', '.join(added_terms) if added_terms else 'nenhuma'}.",
                )
            redirect_url = reverse("clipping_diagnostic")
            query_string = request.POST.get("return_query") or f"client_id={post_client_id}"
            return redirect(f"{redirect_url}?{query_string}")
        messages.error(request, "Acao de diagnostico invalida.")
        return redirect("clipping_diagnostic")

    client_query = (request.GET.get("client") or "Fabio Candido").strip()
    client_id_raw = (request.GET.get("client_id") or "").strip()
    client_id = int(client_id_raw) if client_id_raw.isdigit() else None
    start_raw = request.GET.get("start") or "2026-04-01"
    end_raw = request.GET.get("end") or date.today().isoformat()
    try:
        start = date.fromisoformat(start_raw)
        end = date.fromisoformat(end_raw)
    except ValueError:
        start = date(2026, 4, 1)
        end = date.today()
        output = "Datas invalidas. Use o formato YYYY-MM-DD."
        client_obj = None
    else:
        client_obj, output = build_clipping_diagnostic(client_query, start, end, client_id=client_id)

    return render(
        request,
        "newsclip/diagnostic.html",
        {
            "client_query": client_query,
            "client_id": client_id_raw,
            "client_obj": client_obj,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "output": output,
            "suggested_public_role_variations": suggested_role_variations_for_client(client_obj),
            "return_query": request.GET.urlencode(),
        },
    )


@login_required
def client_news(request, client_id):
    client = get_object_or_404(Client, id=client_id)
    if not user_can_access_client(request.user, client):
        return HttpResponseForbidden("Voce nao tem permissao para ver as noticias deste cliente.")

    page_size = int(request.GET.get("page_size", 20))
    page_number = request.GET.get("page")
    requested_sort = request.GET.get("sort")
    source_filter = request.GET.get("source", "")
    current_search_query = request.GET.get("q", "")
    status_filter = request.GET.get("status", "accepted")
    allowed_sort_orders = {"date-desc", "date-asc", "source"}
    if status_filter == "review":
        allowed_sort_orders.add("priority")
    default_sort_order = "priority" if status_filter == "review" else "date-desc"
    sort_order = requested_sort if requested_sort in allowed_sort_orders else default_sort_order

    revalidate_accepted_articles_for_client(client, limit=150)
    base_articles_qs = Article.objects.filter(client=client, excluded=False)
    status_counts = base_articles_qs.aggregate(
        accepted=Count("id", filter=Q(validation_status="ACCEPTED")),
        review=Count("id", filter=Q(validation_status="REVIEW")),
        rejected=Count("id", filter=Q(validation_status="REJECTED")),
    )
    if status_filter == "review":
        articles_qs = base_articles_qs.filter(validation_status="REVIEW")
    elif status_filter == "rejected":
        articles_qs = base_articles_qs.filter(validation_status="REJECTED")
    else:
        status_filter = "accepted"
        articles_qs = base_articles_qs.filter(validation_status="ACCEPTED")

    if source_filter:
        articles_qs = articles_qs.filter(source__iexact=source_filter)
    if current_search_query:
        articles_qs = apply_article_search(articles_qs, current_search_query)

    if sort_order == "date-asc":
        articles_qs = articles_qs.order_by("published_at")
    elif sort_order == "source":
        articles_qs = articles_qs.order_by("source", "-published_at")
    elif current_search_query and connection.vendor == "postgresql":
        articles_qs = articles_qs.order_by("-search_rank", "-published_at")
    else:
        articles_qs = articles_qs.order_by("-published_at")

    if request.method == "POST":
        acao = request.POST.get("acao")
        ids_selecionados = request.POST.getlist("ids[]") or request.POST.getlist("selected_articles")

        if not ids_selecionados:
            messages.warning(request, "Selecione pelo menos uma noticia.")
        elif acao == "excluir":
            selected_articles = list(
                Article.objects.filter(client=client, id__in=ids_selecionados).select_related("client")
            )
            updated_count = Article.objects.filter(client=client, id__in=ids_selecionados).update(excluded=True)
            record_manual_feedback(selected_articles, "REJECTED", request.user)
            messages.success(request, f"{updated_count} noticia(s) marcada(s) como excluida(s).")
        elif acao == "manter":
            selected_articles = list(
                Article.objects.filter(client=client, id__in=ids_selecionados).select_related("client")
            )
            updated_count = Article.objects.filter(client=client, id__in=ids_selecionados).update(
                excluded=False,
                validation_status="ACCEPTED",
                validation_reason="Aprovada manualmente pelo usuario",
            )
            record_manual_feedback(selected_articles, "ACCEPTED", request.user)
            messages.success(request, f"{updated_count} noticia(s) marcada(s) como mantida(s).")
        else:
            messages.error(request, "Acao invalida.")

        redirect_url = reverse("client_news", args=[client_id])
        query_params = request.GET.urlencode()
        return redirect(f"{redirect_url}?{query_params}" if query_params else redirect_url)

    display_articles = deduplicate_articles_for_display(articles_qs)
    if status_filter == "review" and sort_order == "priority":
        display_articles = sort_review_articles_by_priority(display_articles, client)
    paginator = Paginator(display_articles, page_size)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    display_article_ids = [article.pk for article in display_articles]
    qs_for_charts = Article.objects.filter(pk__in=display_article_ids).exclude(published_at__isnull=True)
    daily_qs = (
        qs_for_charts.annotate(day=TruncDate("published_at"))
        .values("day")
        .annotate(count=Count("id"))
        .order_by("day")
    )
    top_sources_qs = qs_for_charts.values("source").annotate(count=Count("id")).order_by("-count")[:5]
    distinct_sources = articles_qs.order_by("source").values_list("source", flat=True).distinct()

    context = {
        "client": client,
        "articles": page_obj,
        "status_filter": status_filter,
        "status_counts": status_counts,
        "daily_labels_json": json.dumps([d["day"].strftime("%d/%m") for d in daily_qs if d["day"]]),
        "daily_counts_json": json.dumps([d["count"] for d in daily_qs if d["day"]]),
        "source_labels_json": json.dumps([s["source"] for s in top_sources_qs if s["source"]]),
        "source_counts_json": json.dumps([s["count"] for s in top_sources_qs if s["source"]]),
        "page_size": page_size,
        "sort": sort_order,
        "sort_order": sort_order,
        "current_search_query": current_search_query,
        "selected_source_filter": source_filter,
        "selected_source": source_filter,
        "page_size_options": [10, 20, 50, 100],
        "sources_for_filter": distinct_sources,
        "sources": distinct_sources,
        "return_query": request.GET.urlencode(),
    }
    return render(request, "newsclip/client_news.html", context)


@require_POST
@login_required
def bulk_update_news(request, client_id):
    client = get_object_or_404(Client, id=client_id)
    if not user_can_access_client(request.user, client):
        return HttpResponseForbidden()

    action = request.POST.get("action")
    ids = request.POST.getlist("ids[]") or request.POST.getlist("selected_articles")

    if action not in ("exclude", "keep", "validate", "reject", "review") or not ids:
        if request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest":
            return JsonResponse({"error": "Parametros invalidos", "updated": 0}, status=400)
        messages.error(request, "Parametros invalidos ou nenhuma noticia selecionada.")
        return redirect(reverse("client_news", args=[client_id]))

    articles_qs = Article.objects.filter(client=client, id__in=ids)
    feedback_articles = list(articles_qs.select_related("client"))
    updated_ids = list(articles_qs.values_list("id", flat=True))
    if action == "exclude":
        updated_count = articles_qs.update(excluded=True)
        verb = "excluida(s)"
        destination = "excluidas"
        target_status = None
    elif action == "validate":
        updated_count = articles_qs.update(
            excluded=False,
            validation_status="ACCEPTED",
            validation_reason="Validada manualmente pelo usuario",
        )
        verb = "validada(s)"
        destination = "Validadas"
        target_status = "accepted"
    elif action == "reject":
        updated_count = articles_qs.update(
            excluded=False,
            validation_status="REJECTED",
            validation_reason="Invalidada manualmente pelo usuario",
        )
        verb = "movida(s) para Rejeitadas"
        destination = "Rejeitadas"
        target_status = "rejected"
    elif action == "review":
        updated_count = articles_qs.update(
            excluded=False,
            validation_status="REVIEW",
            validation_reason="Movida manualmente para revisao pelo usuario",
        )
        verb = "movida(s) para Revisar"
        destination = "Revisar"
        target_status = "review"
    else:
        updated_count = articles_qs.update(
            excluded=False,
            validation_status="ACCEPTED",
            validation_reason="Marcada como mantida pelo usuario",
        )
        verb = "mantida(s) em Validadas"
        destination = "Validadas"
        target_status = "accepted"

    feedback_decision = {
        "exclude": "REJECTED",
        "reject": "REJECTED",
        "review": "REVIEW",
        "validate": "ACCEPTED",
        "keep": "ACCEPTED",
    }[action]
    feedback_saved = record_manual_feedback(feedback_articles, feedback_decision, request.user)
    message = f"{updated_count} noticia(s) {verb}."
    if action in {"validate", "keep", "reject", "review"} and updated_count:
        message = f"{updated_count} noticia(s) atualizada(s) e movida(s) para a aba {destination}."

    if request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest":
        status_counts = Article.objects.filter(client=client, excluded=False).aggregate(
            accepted=Count("id", filter=Q(validation_status="ACCEPTED")),
            review=Count("id", filter=Q(validation_status="REVIEW")),
            rejected=Count("id", filter=Q(validation_status="REJECTED")),
        )
        return JsonResponse(
            {
                "updated": updated_count,
                "updated_ids": updated_ids,
                "action": action,
                "target_status": target_status,
                "excluded": action == "exclude",
                "message": message,
                "status_counts": status_counts,
                "feedback_saved": feedback_saved,
            }
        )

    messages.success(request, message)
    redirect_url = reverse("client_news", args=[client_id])
    return_query = request.POST.get("return_query") or ""
    return redirect(f"{redirect_url}?{return_query}" if return_query else redirect_url)


@require_POST
@login_required
def fetch_news_view(request, client_id):
    client = get_object_or_404(Client, id=client_id)
    if not user_can_access_client(request.user, client):
        return HttpResponseForbidden("Voce nao tem permissao para buscar noticias para este cliente.")

    active_job = (
        NewsFetchJob.objects.filter(client=client, status__in=["queued", "running"])
        .order_by("-created_at")
        .first()
    )
    if active_job:
        status_url = reverse("check_task_status", args=[active_job.task_id or active_job.pk])
        payload = {
            "status": active_job.status,
            "message": "Ja existe uma busca em andamento para este cliente.",
            "task_id": active_job.task_id or str(active_job.pk),
            "status_url": status_url,
        }
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse(payload, status=202)
        messages.warning(request, payload["message"])
        return redirect("client_news", client_id=client_id)

    job = NewsFetchJob.objects.create(client=client, status="queued")
    task_id = async_task(
        "newsclip.tasks.fetch_news_task",
        client_id,
        job.pk,
        task_name=f"fetch-news-client-{client_id}",
    )
    job.task_id = str(task_id)
    job.save(update_fields=["task_id", "updated_at"])
    allowed_tasks = request.session.get("news_fetch_tasks", {})
    allowed_tasks[str(task_id)] = client_id
    allowed_tasks[str(job.pk)] = client_id
    request.session["news_fetch_tasks"] = allowed_tasks

    message_text = "Busca iniciada em segundo plano."

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse(
            {
                "status": "queued",
                "message": message_text,
                "task_id": str(task_id),
                "status_url": reverse("check_task_status", args=[task_id]),
            },
            status=202,
        )

    messages.success(request, message_text)
    return redirect("client_news", client_id=client_id)


@login_required
def check_task_status(request, task_id):
    from django_q.models import Task

    allowed_client_id = getattr(request, "session", {}).get("news_fetch_tasks", {}).get(str(task_id))
    if allowed_client_id is None:
        return HttpResponseForbidden()

    client = get_object_or_404(Client, pk=allowed_client_id)
    if not user_can_access_client(request.user, client):
        return HttpResponseForbidden()

    job_filter = Q(task_id=str(task_id))
    if str(task_id).isdigit():
        job_filter |= Q(pk=int(task_id))
    job = NewsFetchJob.objects.filter(job_filter, client=client).first()
    if job:
        if job.status in {"queued", "running"} and job.created_at < timezone.now() - timedelta(minutes=45):
            job.status = "failed"
            job.finished_at = timezone.now()
            job.error_message = "Tempo limite excedido ao buscar noticias."
            job.save(update_fields=["status", "finished_at", "error_message", "updated_at"])
        return JsonResponse(
            {
                "success": job.status == "completed",
                "result": job.result_message or job.error_message,
                "started": job.started_at,
                "stopped": job.finished_at,
                "status": job.status,
            }
        )

    try:
        task = Task.objects.get(id=task_id)
        return JsonResponse(
            {
                "success": task.success,
                "result": task.result,
                "started": task.started,
                "stopped": task.stopped,
                "status": "completed" if task.success and task.stopped else ("failed" if task.stopped else "running"),
            }
        )
    except Task.DoesNotExist:
        return JsonResponse({"status": "queued"})


@login_required
def client_reports(request, client_id):
    client = get_object_or_404(Client, pk=client_id)
    if not user_can_access_client(request.user, client):
        return HttpResponseForbidden()

    reports = GeneratedReport.objects.filter(client=client).select_related("created_by")

    return render(
        request,
        "newsclip/client_reports.html",
        {"client": client, "reports": reports, "form": ReportForm(request.POST or None)},
    )


@require_POST
@login_required
def generate_report_view(request, client_id):
    client = get_object_or_404(Client, id=client_id)
    if not user_can_access_client(request.user, client):
        return HttpResponseForbidden()

    form = ReportForm(request.POST)
    if form.is_valid():
        days_str = form.cleaned_data["days"]
        out_format = form.cleaned_data["out_format"]
        label_period = f"ultimos {days_str} dias" if days_str != "all" else "todas as noticias"

        try:
            call_command(
                "generate_report",
                client_id=client_id,
                days=days_str,
                format=out_format,
                created_by_id=request.user.pk,
            )
            messages.success(
                request,
                f"Relatorio ({label_period}, formato {out_format.upper()}) para '{client.name}' gerado com sucesso.",
            )
        except Exception as exc:
            messages.error(request, f"Erro ao iniciar a geracao do relatorio: {exc}")
    else:
        error_list = []
        for field, errors in form.errors.items():
            label = form.fields[field].label if field in form.fields else field
            error_list.extend(f"{label}: {error}" for error in errors)
        messages.error(request, "Formulario invalido. " + " | ".join(error_list))

    return redirect("client_reports", client_id=client_id)


@login_required
def download_report(request, client_id, report_id):
    client = get_object_or_404(Client, pk=client_id)
    if not user_can_access_client(request.user, client):
        return HttpResponseForbidden()

    report = get_object_or_404(GeneratedReport, pk=report_id, client=client)
    response = HttpResponse(bytes(report.content), content_type=report.content_type)
    response["Content-Disposition"] = f'attachment; filename="{report.filename}"'
    response["Content-Length"] = report.size
    return response
