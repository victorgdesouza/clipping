# newsclip/views.py
import os
import json
import pathlib # pathlib foi usado em client_reports
import csv
from datetime import timedelta # datetime foi usado em alguma versão anterior, mantendo por segurança

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.mixins import LoginRequiredMixin # UserPassesTestMixin não estava sendo usado
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger # EmptyPage, PageNotAnInteger não estavam sendo explicitamente tratados, mas bom ter
from django.core.management import call_command
# Removido: from django.core.management.base import BaseCommand (não usado aqui)
from django.db.models import Q, F, Count # F não estava sendo usado, Count sim
from django.db.models.functions import TruncDate
from django.http import (
    HttpResponseForbidden,
    FileResponse,
    Http404,
    HttpResponseBadRequest, # Usado em fetch_news_view
    JsonResponse
)
from django.shortcuts import redirect, get_object_or_404, render
from django.urls import reverse_lazy, reverse # reverse usado
from django.utils import timezone # timezone usado
from django.utils.text import slugify # slugify usado
from django.views.generic import CreateView, UpdateView, ListView
from django.views.decorators.http import require_POST # require_POST usado

# Modelos e Formulários do App
from .models import Client, Article # Removido Topic se não for um modelo aqui, Article duplicado removido
from .forms import ReportForm # ClientForm foi removido desta linha

# ----- IMPORTS PARA BUSCA FULL-TEXT -----
# Usaremos SearchQuery. SearchRank e SearchVector (a função) são mais para PostgreSQL.
# Para compatibilidade com SQLite, focaremos em SearchQuery.
from django.contrib.postgres.search import SearchQuery
# -------------------------------------------


# 1) Cadastro de usuário
class SignUpView(CreateView):
    template_name = "registration/signup.html" # Corrigido para estar dentro de registration, comum
    form_class = UserCreationForm
    success_url = reverse_lazy("login")


# 3) Cadastro de clientes
class ClientCreateView(LoginRequiredMixin, CreateView):
    model = Client
    fields = ["name", "keywords", "domains", "instagram", "x", "youtube"]
    template_name = "newsclip/client_form.html"
    
    def get_success_url(self): # Usar get_success_url para dashboards dinâmicos
        return reverse('dashboard')

    def form_valid(self, form):
        form.instance.created_by = self.request.user # Exemplo de como associar o criador
        response = super().form_valid(form)
        # Adiciona automaticamente o usuário logado como responsável se o campo 'users' existir e for M2M
        if hasattr(self.object, 'users') and callable(getattr(self.object.users, 'add', None)):
             self.object.users.add(self.request.user)
        return response

class ClientUpdateView(LoginRequiredMixin, UpdateView): # Adicionado LoginRequiredMixin
    model = Client
    fields = ["name", "keywords", "domains", "instagram", "x", "youtube"]
    template_name = "newsclip/client_form.html"

    def get_success_url(self):
        return reverse('dashboard')

    def form_valid(self, form):
        response = super().form_valid(form)
        # Garante que o usuário logado está associado, se o campo 'users' existir
        if hasattr(self.object, 'users') and callable(getattr(self.object.users, 'all', None)):
            if self.request.user not in self.object.users.all():
                if callable(getattr(self.object.users, 'add', None)):
                    self.object.users.add(self.request.user)
        return response

# Esta view parece listar clientes e algumas de suas notícias, não é uma busca de "todas as notícias"
# A chamada a `buscar_noticias_para_cliente` foi removida pois causava ImportError e sua lógica não está aqui
class BuscarTodasNoticiasView(LoginRequiredMixin, ListView): # Adicionado LoginRequiredMixin
    template_name = 'newsclip/todas_noticias.html'
    context_object_name = 'clientes_data' # Renomeado para evitar conflito com 'clientes' do queryset de Client

    def get_queryset(self):
        # Retorna os clientes associados ao usuário ou todos se for superuser
        if self.request.user.is_superuser:
            return Client.objects.all().order_by('name')
        elif hasattr(self.request.user, 'clients'): # Verifica se a relação reversa existe
            return self.request.user.clients.all().order_by('name')
        return Client.objects.none() # Retorna queryset vazio se não for superuser e não tiver clientes associados

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        clientes = context[self.context_object_name] # Usa o nome de contexto correto
        clientes_noticias_display = []
        for cliente_obj in clientes: # Renomeado para evitar conflito
            artigos = Article.objects.filter(client=cliente_obj, excluded=False).order_by('-published_at')[:5]
            total_artigos = Article.objects.filter(client=cliente_obj, excluded=False).count()
            clientes_noticias_display.append({
                'cliente': cliente_obj,
                'noticias': artigos,
                'total': total_artigos,
            })
        context['clientes_noticias_display'] = clientes_noticias_display
        # Adicionar um campo de busca geral aqui, se desejado, precisaria de um formulário e lógica de filtragem
        # context['search_query'] = self.request.GET.get('q', '')
        return context

def noticias_cliente_json(request, pk):
    # Adicionar checagem de permissão seria bom aqui
    artigos = Article.objects.filter(client_id=pk, excluded=False).order_by('-published_at')
    dados = []
    for artigo in artigos:
        dados.append({
            "id": artigo.id, # Adicionado ID para referência
            "title": artigo.title,
            "source": artigo.source,
            "published_at": artigo.published_at.strftime("%d/%m/%Y %H:%M") if artigo.published_at else "N/A",
            "url": artigo.url,
            "excluded": artigo.excluded
        })
    return JsonResponse({"noticias": dados})


@login_required
def dashboard(request):
    # Se o modelo Client tem um campo 'users' (M2M com User) ou 'created_by' (FK para User)
    if request.user.is_superuser:
        clients_qs = Client.objects.all()
    elif hasattr(request.user, 'clients'): # Relação M2M 'clients' no User ou Client
        clients_qs = request.user.clients.all()
    # Adicionar outra lógica de filtragem se a relação for diferente, ex: created_by
    # elif Client.objects.filter(created_by=request.user).exists():
    #    clients_qs = Client.objects.filter(created_by=request.user)
    else:
        clients_qs = Client.objects.none() # Nenhum cliente se não for superuser e não houver relação clara
        
    return render(request, "newsclip/dashboard.html", {"clients": clients_qs})


@login_required
def client_news(request, client_id):
    client = get_object_or_404(Client, id=client_id)

    can_access = False
    if request.user.is_superuser:
        can_access = True
    elif hasattr(client, 'users') and callable(getattr(client.users, 'all', None)):
        if request.user in client.users.all():
            can_access = True

    if not can_access:
        return HttpResponseForbidden("Você não tem permissão para ver as notícias deste cliente.")

    page_size = int(request.GET.get("page_size", 20))
    page_number = request.GET.get("page")
    sort_order = request.GET.get("sort", "date-desc")
    source_filter = request.GET.get("source", "")
    current_search_query = request.GET.get('q', '')

    articles_qs = Article.objects.filter(client=client, excluded=False)

    if source_filter:
        articles_qs = articles_qs.filter(source__iexact=source_filter)

    if current_search_query:
        query_fts = SearchQuery(current_search_query, search_type='plain')
        articles_qs = articles_qs.filter(search_vector=query_fts)

    # CORREÇÃO AQUI para usar published_at consistentemente
    if sort_order == "date-asc":
        articles_qs = articles_qs.order_by("published_at")
    elif sort_order == "source":
        articles_qs = articles_qs.order_by("source", "-published_at")
    else: 
        articles_qs = articles_qs.order_by("-published_at")


    if request.method == "POST":
        acao = request.POST.get('acao')
        ids_selecionados = request.POST.getlist('ids[]') or request.POST.getlist('selected_articles')

        if not ids_selecionados:
            messages.warning(request, "Selecione pelo menos uma notícia.")
        else:
            if acao == "excluir":
                updated_count = Article.objects.filter(client=client, id__in=ids_selecionados).update(excluded=True)
                messages.success(request, f"{updated_count} notícia(s) marcada(s) como excluída(s).")
            elif acao == "manter":
                updated_count = Article.objects.filter(client=client, id__in=ids_selecionados).update(excluded=False)
                messages.success(request, f"{updated_count} notícia(s) marcada(s) como mantida(s).")
            else:
                messages.error(request, "Ação inválida.")

        redirect_url = reverse('client_news', args=[client_id])
        query_params = request.GET.urlencode()
        if query_params:
            return redirect(f"{redirect_url}?{query_params}")
        return redirect(redirect_url)

    paginator = Paginator(articles_qs, page_size)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    # CORREÇÃO AQUI para usar published_at
    qs_for_charts = articles_qs.exclude(published_at__isnull=True) 

    daily_qs = (
        qs_for_charts
        .annotate(day=TruncDate("published_at")) # CORREÇÃO AQUI
        .values("day")
        .annotate(count=Count("id"))
        .order_by("day")
    )
    daily_labels = [d["day"].strftime("%d/%m") for d in daily_qs if d["day"]]
    daily_counts = [d["count"] for d in daily_qs if d["day"]]

    top_sources_qs = (
        qs_for_charts
        .values("source")
        .annotate(count=Count("id"))
        .order_by("-count")[:5]
    )
    source_labels = [s["source"] for s in top_sources_qs if s["source"]]
    source_counts = [s["count"] for s in top_sources_qs if s["source"]]

    distinct_sources = articles_qs.order_by('source').values_list("source", flat=True).distinct()

    context = {
        "client": client,
        "articles": page_obj,
        "daily_labels_json": json.dumps(daily_labels),
        "daily_counts_json": json.dumps(daily_counts),
        "source_labels_json": json.dumps(source_labels),
        "source_counts_json": json.dumps(source_counts),
        "page_size": page_size,
        "sort": sort_order,  # Added for template compatibility
        "sort_order": sort_order,
        "current_search_query": current_search_query,
        "selected_source_filter": source_filter,
        "selected_source": source_filter,  # Added for template compatibility
        "page_size_options": [10, 20, 50, 100],
        "sources_for_filter": distinct_sources,
        "sources": distinct_sources,  # Added for template compatibility
    }
    return render(request, "newsclip/client_news.html", context)

@require_POST
@login_required
def bulk_update_news(request, client_id): # Esta view está duplicada, remover uma delas
    client = get_object_or_404(Client, id=client_id)
    # Checagem de permissão (similar à client_news)
    # ... (adicionar lógica de permissão) ...

    action = request.POST.get("action")
    ids = request.POST.getlist("ids[]") or request.POST.getlist("selected_articles")

    if action not in ("exclude", "keep") or not ids:
        if request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest":
            return JsonResponse({"error": "Parâmetros inválidos", "updated": 0}, status=400)
        messages.error(request, "Parâmetros inválidos ou nenhuma notícia selecionada.")
        return redirect(reverse('client_news', args=[client_id])) # Redireciona de volta

    articles_qs = Article.objects.filter(client=client, id__in=ids)
    updated_count = 0 # Inicializa o contador
    verb = ""

    if action == "exclude":
        updated_count = articles_qs.update(excluded=True)
        verb = "excluídas"
    elif action == "keep": # Use elif para clareza
        updated_count = articles_qs.update(excluded=False)
        verb = "marcadas como mantidas"

    if request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest":
        return JsonResponse({
            "updated": updated_count,
            "message": f"{updated_count} notícia(s) {verb}."
        })

    messages.success(request, f"{updated_count} notícia(s) {verb}.")
    # Preservar query params no redirect após bulk update também
    redirect_url = reverse('client_news', args=[client_id])
    query_params = request.GET.urlencode() # GET pode estar vazio aqui se o POST não os passou, idealmente o form do POST deveria incluir os query params atuais
    if query_params:
        return redirect(f"{redirect_url}?{query_params}")
    return redirect(redirect_url)


@login_required
def fetch_news_view(request, client_id):
    # Adicionar checagem de permissão para o cliente
    client = get_object_or_404(Client, id=client_id)
    # ... (lógica de permissão similar à client_news) ...
    if not (request.user.is_superuser or (hasattr(client, 'users') and request.user in client.users.all()) ): # Exemplo simplificado
         return HttpResponseForbidden("Você não tem permissão para buscar notícias para este cliente.")

    if request.method != "POST":
        return HttpResponseBadRequest("Método inválido. Use POST.")
    
    try:
        # Run synchronously
        call_command('fetch_news', client_id=client_id)
        
        message_text = "Busca de notícias concluída com sucesso!"
        status_ok = True
        
    except Exception as e:
        message_text = f"Erro ao buscar notícias: {str(e)}"
        status_ok = False
        print(f"Error running fetch_news: {e}")
        import traceback
        traceback.print_exc()

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({
            "status": "ok" if status_ok else "error", 
            "message": message_text,
        })
    
    if status_ok:
        messages.success(request, message_text)
    else:
        messages.error(request, message_text)
    return redirect("client_news", client_id=client_id)



@login_required
def check_task_status(request, task_id):
    from django_q.models import Task
    try:
        task = Task.objects.get(id=task_id)
        return JsonResponse({
            "success": task.success,
            "result": task.result,
            "started": task.started,
            "stopped": task.stopped,
            "status": "DONE" if task.stopped else "RUNNING"
        })
    except Task.DoesNotExist:
        return JsonResponse({"status": "PENDING"}) # Ou erro, dependendo da lógica



@login_required
def client_reports(request, client_id):
    client = get_object_or_404(Client, pk=client_id)
    if not (request.user.is_superuser or (hasattr(client, 'users') and request.user in client.users.all())):
        return HttpResponseForbidden()

    reports_media_path = pathlib.Path(settings.MEDIA_ROOT) / "reports"
    reports_media_path.mkdir(parents=True, exist_ok=True) # Garante que o diretório existe
    
    client_slug = slugify(client.name)
    
    # Considerar ordenar por data de modificação do arquivo para pegar os mais recentes
    # Cuidado com muitos arquivos, glob pode ser lento.
    # Talvez armazenar referências a relatórios no banco de dados seja melhor a longo prazo.
    try:
        files = sorted(
            [f for f in reports_media_path.glob(f"relatorio_{client_slug}_*.*") if f.is_file()],
            key=lambda f: f.stat().st_mtime, # Ordenar por data de modificação
            reverse=True
        )
        file_names = [f.name for f in files]
    except FileNotFoundError:
        file_names = []


    form = ReportForm(request.POST or None)
    return render(request, "newsclip/client_reports.html", {
        "client": client,
        "files": file_names,
        "form": form,
    })

@require_POST
@login_required
def generate_report_view(request, client_id):
    client = get_object_or_404(Client, id=client_id)
    if not (request.user.is_superuser or (hasattr(client, 'users') and request.user in client.users.all())):
        return HttpResponseForbidden()

    # request.method == "POST" é garantido por @require_POST
    form = ReportForm(request.POST)
    if form.is_valid():
        days_str = form.cleaned_data["days"]
        out_format = form.cleaned_data["out_format"]

        label_period = f"últimos {days_str} dias" if days_str != "all" else "todas as notícias"
        
        try:
            call_command(
                "generate_report",
                client_id=client_id,
                days=days_str,
                format=out_format # 'format' é um nome comum, mas cuidado para não sombrear built-in se usar em outro contexto
            )
            messages.success(
                request,
                f"Geração de relatório ({label_period}, formato {out_format.upper()}) para o cliente '{client.name}' foi iniciada."
            )
        except Exception as e:
            messages.error(request, f"Erro ao iniciar a geração do relatório: {e}")
            # Logar o erro 'e' no servidor para debug

    else:
        # Coletar erros do formulário para exibir mensagens mais detalhadas
        error_list = []
        for field, errors in form.errors.items():
            for error in errors:
                error_list.append(f"{form.fields[field].label if field in form.fields else field}: {error}")
        messages.error(request, "Formulário inválido. " + " | ".join(error_list))
    
    return redirect("client_reports", client_id=client_id)


@login_required
def download_report(request, client_id, filename):
    client = get_object_or_404(Client, pk=client_id)
    if not (request.user.is_superuser or (hasattr(client, 'users') and request.user in client.users.all())):
        return HttpResponseForbidden()

    # Validar o filename para evitar LFI (Local File Inclusion) - MUITO IMPORTANTE
    # Garanta que o filename não contém '..' ou começa com '/'
    if ".." in filename or filename.startswith("/"):
        raise Http404("Nome de arquivo inválido.")

    path_to_file = pathlib.Path(settings.MEDIA_ROOT) / "reports" / filename
    
    if not path_to_file.exists() or not path_to_file.is_file():
        raise Http404(f"Arquivo '{filename}' não encontrado ou não é um arquivo válido.")
    
    # Checagem adicional para garantir que o arquivo está dentro do diretório esperado (defesa em profundidade)
    try:
        path_to_file.resolve().relative_to(pathlib.Path(settings.MEDIA_ROOT) / "reports")
    except ValueError:
        raise Http404("Acesso ao arquivo fora do diretório permitido.")

    try:
        # Tenta adivinhar o content_type, mas pode ser genérico
        import mimetypes
        content_type, encoding = mimetypes.guess_type(filename)
        if content_type is None:
            content_type = 'application/octet-stream' # Fallback genérico

        return FileResponse(open(path_to_file, "rb"), as_attachment=True, filename=filename, content_type=content_type)
    except FileNotFoundError:
        raise Http404(f"Arquivo '{filename}' não foi encontrado no servidor (FileNotFoundError).")
    except Exception as e:
        # Logar o erro 'e' para o administrador
        messages.error(request, "Ocorreu um erro ao tentar baixar o relatório.")
        # Redirecionar para a página de relatórios ou dashboard pode ser melhor que um Http404 genérico aqui
        return redirect(reverse('client_reports', args=[client_id]))



