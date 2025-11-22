from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.contrib.postgres.search import SearchVectorField
from django.contrib.postgres.indexes import GinIndex

created_at = models.DateTimeField(auto_now_add=True, default=timezone.now)


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
    
    # Campos opcionais para Scrape
    title_selector = models.CharField("Seletor de Título (CSS)", max_length=200, blank=True, null=True)
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
    level = models.CharField("Nível", max_length=20, choices=LEVELS, default='INFO')
    message = models.TextField("Mensagem")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.created_at.strftime('%d/%m %H:%M')}] {self.level}: {self.message[:50]}"


class Client(models.Model):
    name    = models.CharField("Nome do cliente", max_length=500)
    keywords= models.TextField(help_text="Separe por vírgulas")
    instagram = models.CharField("Instagram (@...)", max_length=100, blank=True)
    x = models.CharField("X/Twitter (@...)", max_length=100, blank=True)
    youtube = models.CharField("YouTube (canal/usuário)", max_length=200, blank=True)
    domains = models.TextField(
        "Domínios confiáveis (vírgula-separados)",
        blank=True,
        help_text="Ex: g1.globo.com, uol.com.br"
    )
    users   = models.ManyToManyField(get_user_model(), related_name="clients",
                                     help_text="Quem pode ver/editar este cliente")

    def __str__(self):
        return self.name


class Article(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="articles", db_index=True) # Adicionado db_index=True se ainda não tiver
    title = models.CharField("Título", max_length=255, db_index=True) # Adicionado db_index=True
    url = models.TextField("Link", unique=True) # Considere mudar para URLField se fizer mais sentido: models.URLField("Link", max_length=500, unique=True)

    # ----- ADICIONAR ESTE CAMPO -----
    content = models.TextField("Conteúdo", blank=True, null=True)
    # ---------------------------------

    summary = models.TextField("Resumo", blank=True, null=True) # Adicionado null=True para consistência se pode ser vazio

    # Se você tem um modelo Topic, o ideal seria:
    # topic = models.ForeignKey(Topic, on_delete=models.SET_NULL, null=True, blank=True, related_name='articles', db_index=True)
    # Se Topic for apenas um texto, mantenha como CharField, mas adicione db_index:
    topic = models.CharField("Tópico", max_length=255, blank=True, db_index=True) # Adicionado db_index=True

    published_at = models.DateTimeField("Publicação", null=True, blank=True, db_index=True)
    source = models.CharField("Fonte", max_length=255, blank=True, db_index=True) # Adicionado db_index=True
    excluded = models.BooleanField("Excluído manualmente", default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Adicionar updated_at se ainda não existir, é uma boa prática:
    updated_at = models.DateTimeField("Atualizado em", auto_now=True, null=True, blank=True)


    search_vector = SearchVectorField(null=True, blank=True) # Este você já tinha

    class Meta:
        ordering = ['-published_at']
        indexes = [
            GinIndex(fields=['search_vector']),
            # Você pode adicionar outros índices aqui se necessário, por exemplo:
            # models.Index(fields=['client', '-published_at']),
        ]
        verbose_name = "Notícia" # Adicionar se quiser nomes amigáveis no admin
        verbose_name_plural = "Notícias" # Adicionar se quiser nomes amigáveis no admin

    def __str__(self):
        # Ajustado para evitar erro se client ou title for None (embora title seja obrigatório)
        client_name = self.client.name if self.client else "Sem Cliente"
        title_short = (self.title[:47] + "...") if self.title and len(self.title) > 50 else self.title
        return f"{client_name}: {title_short}"

    @property
    def title_truncado(self): # Propriedade que você usou em um print em utils.py
        return (self.title[:47] + "...") if self.title and len(self.title) > 50 else self.title