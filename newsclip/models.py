from django.conf import settings
from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.postgres.search import SearchVectorField
from django.contrib.postgres.indexes import GinIndex


class Source(models.Model):
    SOURCE_TYPES = [
        ('RSS', 'RSS Feed'),
        ('SCRAPE', 'Web Scrape'),
        ('API', 'API (NewsAPI/NewsData)'),
        ('DISCOVERED', 'Descoberta automatica'),
        ('SITEMAP', 'Sitemap'),
        ('NEWS_SITEMAP', 'Google News Sitemap'),
        ('YOUTUBE', 'Canal do YouTube'),
    ]
    STATUS_CHOICES = [
        ('CANDIDATE', 'Candidata'),
        ('VERIFIED', 'Verificada'),
        ('ACTIVE', 'Ativa'),
        ('DEGRADED', 'Com falhas'),
        ('BLOCKED', 'Bloqueada'),
        ('DISCARDED', 'Descartada'),
    ]
    name = models.CharField("Nome da Fonte", max_length=200)
    url = models.URLField("URL do Feed/Site", max_length=500)
    source_type = models.CharField("Tipo", max_length=20, choices=SOURCE_TYPES, default='RSS')
    is_active = models.BooleanField("Ativa?", default=True)
    domain = models.CharField("Dominio", max_length=255, blank=True, db_index=True)
    status = models.CharField("Status", max_length=20, choices=STATUS_CHOICES, default='ACTIVE', db_index=True)
    discovered_automatically = models.BooleanField("Descoberta automaticamente?", default=False)
    discovery_provider = models.CharField("Provedor de descoberta", max_length=50, blank=True)
    confidence_score = models.PositiveSmallIntegerField("Confianca", default=0)
    discovery_count = models.PositiveIntegerField("Vezes descoberta", default=0)
    first_discovered_at = models.DateTimeField("Primeira descoberta", null=True, blank=True)
    last_discovered_at = models.DateTimeField("Ultima descoberta", null=True, blank=True)
    title_selector = models.CharField("Seletor de Titulo (CSS)", max_length=200, blank=True, null=True)
    link_selector = models.CharField("Seletor de Link (CSS)", max_length=200, blank=True, null=True)
    date_selector = models.CharField("Seletor de Data (CSS)", max_length=200, blank=True, null=True)

    def __str__(self):
        return f"{self.name} ({self.get_source_type_display()})"


class SourceEndpoint(models.Model):
    ENDPOINT_TYPES = [
        ('RSS', 'RSS/Atom'),
        ('SITEMAP', 'Sitemap'),
        ('NEWS_SITEMAP', 'Google News Sitemap'),
        ('YOUTUBE', 'YouTube'),
        ('WEB', 'Pagina web'),
    ]

    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="endpoints")
    endpoint_type = models.CharField(max_length=20, choices=ENDPOINT_TYPES, db_index=True)
    url = models.URLField(max_length=1000)
    is_active = models.BooleanField(default=True, db_index=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error_at = models.DateTimeField(null=True, blank=True)
    consecutive_errors = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source", "url"], name="unique_endpoint_url_per_source"),
        ]

    def __str__(self):
        return f"{self.source.name}: {self.get_endpoint_type_display()}"


class DiscoveryResult(models.Model):
    client = models.ForeignKey('Client', on_delete=models.CASCADE, related_name="discovery_results")
    source = models.ForeignKey(Source, on_delete=models.SET_NULL, related_name="discovery_results", null=True, blank=True)
    provider = models.CharField(max_length=50, db_index=True)
    query = models.TextField()
    title = models.CharField(max_length=500)
    url = models.URLField(max_length=2000)
    description = models.TextField(blank=True)
    relevance_score = models.PositiveSmallIntegerField(default=0)
    is_relevant = models.BooleanField(default=False, db_index=True)
    discovered_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["client", "provider", "-discovered_at"]),
        ]

    def __str__(self):
        return f"{self.provider}: {self.title[:80]}"


class DiscoveryRun(models.Model):
    STATUS_CHOICES = [
        ("RUNNING", "Em execucao"),
        ("SUCCESS", "Concluida"),
        ("PARTIAL", "Parcial"),
        ("ERROR", "Erro"),
    ]

    client = models.ForeignKey('Client', on_delete=models.CASCADE, related_name="discovery_runs")
    provider = models.CharField(max_length=50, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="RUNNING", db_index=True)
    queries_count = models.PositiveIntegerField(default=0)
    results_count = models.PositiveIntegerField(default=0)
    relevant_count = models.PositiveIntegerField(default=0)
    articles_count = models.PositiveIntegerField(default=0)
    new_sources_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["client", "provider", "-started_at"]),
        ]

    def __str__(self):
        return f"{self.client}: {self.provider} ({self.status})"


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
    excluded_keywords = models.TextField(
        "Termos excluidos",
        blank=True,
        help_text="Separe por virgulas. Noticias que contenham estes termos nao serao salvas.",
    )
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
    VALIDATION_CHOICES = [
        ("ACCEPTED", "Validada"),
        ("REVIEW", "Revisar"),
        ("REJECTED", "Rejeitada"),
    ]
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="articles", db_index=True)
    title = models.CharField("Titulo", max_length=255, db_index=True)
    url = models.TextField("Link")
    content = models.TextField("Conteudo", blank=True, null=True)
    summary = models.TextField("Resumo", blank=True, null=True)
    topic = models.CharField("Topico", max_length=255, blank=True, db_index=True)
    published_at = models.DateTimeField("Publicacao", null=True, blank=True, db_index=True)
    source = models.CharField("Fonte", max_length=255, blank=True, db_index=True)
    excluded = models.BooleanField("Excluido manualmente", default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True, null=True, blank=True)
    search_vector = SearchVectorField(null=True, blank=True)
    dedup_key = models.CharField(max_length=96, blank=True, db_index=True)
    provider = models.CharField(max_length=32, default="OTHER", db_index=True)
    relevance_score = models.PositiveSmallIntegerField(default=0, db_index=True)
    validation_status = models.CharField(
        max_length=16,
        choices=VALIDATION_CHOICES,
        default="ACCEPTED",
        db_index=True,
    )
    validation_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-published_at']
        indexes = [
            GinIndex(fields=['search_vector']),
        ]
        constraints = [
            models.UniqueConstraint(fields=['client', 'url'], name='unique_article_url_per_client'),
            models.UniqueConstraint(fields=['client', 'dedup_key'], name='unique_article_dedup_per_client'),
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


class GeneratedReport(models.Model):
    FORMAT_CHOICES = [
        ("pdf", "PDF"),
        ("xlsx", "Excel"),
        ("csv", "CSV"),
    ]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="generated_reports")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="generated_reports",
        null=True,
        blank=True,
    )
    filename = models.CharField(max_length=255)
    format = models.CharField(max_length=10, choices=FORMAT_CHOICES)
    period_label = models.CharField(max_length=50)
    content_type = models.CharField(max_length=100)
    content = models.BinaryField()
    size = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["client", "filename"], name="unique_report_filename_per_client")
        ]

    def __str__(self):
        return f"{self.client}: {self.filename}"
