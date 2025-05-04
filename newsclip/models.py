from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone

created_at = models.DateTimeField(auto_now_add=True, default=timezone.now)

source = models.CharField("Fonte", max_length=500, blank=True)  # antes era 200

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
    client       = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="articles")
    title        = models.CharField("Título", max_length=500)
    url = models.TextField("Link", unique=True)

    published_at = models.DateTimeField("Publicação", null=True, blank=True, db_index=True)
    source       = models.CharField("Fonte", max_length=500, blank=True)
    summary      = models.TextField("Resumo", blank=True)
    topic        = models.CharField("Tópico", max_length=500, blank=True)
    excluded     = models.BooleanField("Excluído manualmente", default=False)
    created_at   = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.client.name}: {self.title[:50]}..."

    class Meta:
        ordering = ['-published_at']

