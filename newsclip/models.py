from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.postgres.search import SearchVectorField
from django.contrib.postgres.indexes import GinIndex


class Source(models.Model):
    SOURCE_TYPES = [
        ('RSS', 'RSS Feed'),
        ('SCRAPE', 'Web Scrape'),
        ('API', 'API (NewsAPI/NewsData)'),
    ]
    name = models.CharField("Nome da Fonte", max_length=200)
    url = models.URLField("URL do Feed/Site", max_length=500)
    source_type = models.CharField("Tipo", max_length=20, choices=SOURCE_TYPES, default='RSS')
    is_active = models.BooleanField("Ativa?", default=True)
    title_selector = models.CharField("Seletor de Titulo (CSS)", max_length=200, blank=True, null=True)
    link_selector = models.CharField("Seletor de Link (CSS)", max_length=200, blank=True, null=True)
    date_selector = models.CharField("Seletor de Data (CSS)", max_length=200, blank=True, null=True)

    def __str__(self):
        return f"{self.name} ({self.get_source_type_display()})"


class FetchLog(models.Model):
    LEVELS = [
        ('INFO', 'Info'),
        ('WARNING', 'Aviso'),
        ('ERROR', 'Erro'),
        ('SUCCESS', 'Sucesso'),
    ]
    client = models.ForeignKey('Client', on_delete=models.CASCADE, related_name='fetch_logs', null=True, blank=True)
    source = models.ForeignKey(Source, on_delete=models.SET_NULL, null=True, blank=True)
    level = models.CharField("Nivel", max_length=20, choices=LEVELS, default='INFO')
    message = models.TextField("Mensagem")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.created_at.strftime('%d/%m %H:%M')}] {self.level}: {self.message[:50]}"


class Client(models.Model):
    name = models.CharField("Nome do cliente", max_length=500)
    keywords = models.TextField(help_text="Separe por virgulas")
    instagram = models.CharField("Instagram (@...)", max_length=100, blank=True)
    x = models.CharField("X/Twitter (@...)", max_length=100, blank=True)
    youtube = models.CharField("YouTube (canal/usuario)", max_length=200, blank=True)
    domains = models.TextField(
        "Dominios confiaveis (virgula-separados)",
        blank=True,
        help_text="Ex: g1.globo.com, uol.com.br",
    )
    users = models.ManyToManyField(
        get_user_model(),
        related_name="clients",
        help_text="Quem pode ver/editar este cliente",
    )

    def __str__(self):
        return self.name


class Article(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="articles", db_index=True)
    title = models.CharField("Titulo", max_length=255, db_index=True)
    url = models.TextField("Link", unique=True)
    content = models.TextField("Conteudo", blank=True, null=True)
    summary = models.TextField("Resumo", blank=True, null=True)
    topic = models.CharField("Topico", max_length=255, blank=True, db_index=True)
    published_at = models.DateTimeField("Publicacao", null=True, blank=True, db_index=True)
    source = models.CharField("Fonte", max_length=255, blank=True, db_index=True)
    excluded = models.BooleanField("Excluido manualmente", default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True, null=True, blank=True)
    search_vector = SearchVectorField(null=True, blank=True)

    class Meta:
        ordering = ['-published_at']
        indexes = [
            GinIndex(fields=['search_vector']),
        ]
        verbose_name = "Noticia"
        verbose_name_plural = "Noticias"

    def __str__(self):
        client_name = self.client.name if self.client else "Sem Cliente"
        title_short = (self.title[:47] + "...") if self.title and len(self.title) > 50 else self.title
        return f"{client_name}: {title_short}"

    @property
    def title_truncado(self):
        return (self.title[:47] + "...") if self.title and len(self.title) > 50 else self.title
