import json

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
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from .forms import ClientForm, ReportForm
from .models import Article, Client, GeneratedReport


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
            artigos = Article.objects.filter(client=cliente, excluded=False).order_by("-published_at")[:5]
            total_artigos = Article.objects.filter(client=cliente, excluded=False).count()
            clientes_noticias_display.append(
                {
                    "cliente": cliente,
                    "noticias": artigos,
                    "total": total_artigos,
                }
            )

        context["clientes_noticias_display"] = clientes_noticias_display
        return context


def noticias_cliente_json(request, pk):
    client = get_object_or_404(Client, pk=pk)
    if not request.user.is_authenticated or not user_can_access_client(request.user, client):
        return HttpResponseForbidden()

    artigos = Article.objects.filter(client=client, excluded=False).order_by("-published_at")
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
    return render(request, "newsclip/dashboard.html", {"clients": clients_for_user(request.user)})


@login_required
def client_news(request, client_id):
    client = get_object_or_404(Client, id=client_id)
    if not user_can_access_client(request.user, client):
        return HttpResponseForbidden("Voce nao tem permissao para ver as noticias deste cliente.")

    page_size = int(request.GET.get("page_size", 20))
    page_number = request.GET.get("page")
    sort_order = request.GET.get("sort", "date-desc")
    source_filter = request.GET.get("source", "")
    current_search_query = request.GET.get("q", "")

    articles_qs = Article.objects.filter(client=client, excluded=False)

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
            updated_count = Article.objects.filter(client=client, id__in=ids_selecionados).update(excluded=True)
            messages.success(request, f"{updated_count} noticia(s) marcada(s) como excluida(s).")
        elif acao == "manter":
            updated_count = Article.objects.filter(client=client, id__in=ids_selecionados).update(excluded=False)
            messages.success(request, f"{updated_count} noticia(s) marcada(s) como mantida(s).")
        else:
            messages.error(request, "Acao invalida.")

        redirect_url = reverse("client_news", args=[client_id])
        query_params = request.GET.urlencode()
        return redirect(f"{redirect_url}?{query_params}" if query_params else redirect_url)

    paginator = Paginator(articles_qs, page_size)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    qs_for_charts = articles_qs.exclude(published_at__isnull=True)
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

    if action not in ("exclude", "keep") or not ids:
        if request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest":
            return JsonResponse({"error": "Parametros invalidos", "updated": 0}, status=400)
        messages.error(request, "Parametros invalidos ou nenhuma noticia selecionada.")
        return redirect(reverse("client_news", args=[client_id]))

    articles_qs = Article.objects.filter(client=client, id__in=ids)
    if action == "exclude":
        updated_count = articles_qs.update(excluded=True)
        verb = "excluidas"
    else:
        updated_count = articles_qs.update(excluded=False)
        verb = "marcadas como mantidas"

    if request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest":
        return JsonResponse({"updated": updated_count, "message": f"{updated_count} noticia(s) {verb}."})

    messages.success(request, f"{updated_count} noticia(s) {verb}.")
    return redirect(reverse("client_news", args=[client_id]))


@require_POST
@login_required
def fetch_news_view(request, client_id):
    client = get_object_or_404(Client, id=client_id)
    if not user_can_access_client(request.user, client):
        return HttpResponseForbidden("Voce nao tem permissao para buscar noticias para este cliente.")

    try:
        call_command("fetch_news", client_id=client_id)
        message_text = "Busca finalizada."
        status_ok = True
    except Exception as exc:
        message_text = f"Erro ao buscar noticias: {exc}"
        status_ok = False

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"status": "ok" if status_ok else "error", "message": message_text})

    if status_ok:
        messages.success(request, message_text)
    else:
        messages.error(request, message_text)
    return redirect("client_news", client_id=client_id)


@login_required
def check_task_status(request, task_id):
    from django_q.models import Task

    if not request.user.is_superuser:
        return HttpResponseForbidden()

    try:
        task = Task.objects.get(id=task_id)
        return JsonResponse(
            {
                "success": task.success,
                "result": task.result,
                "started": task.started,
                "stopped": task.stopped,
                "status": "DONE" if task.stopped else "RUNNING",
            }
        )
    except Task.DoesNotExist:
        return JsonResponse({"status": "PENDING"})


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
