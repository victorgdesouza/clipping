from django.db import models
from django.conf import settings
from newsclip.models import Client

COVERAGE_CHOICES = [
    ('release','Release'),
    ('artigo','Artigo'),
    ('nota','Nota'),
    ('post','Post'),
    ('espontaneo','Espontâneo'),
]

MEDIA_CHOICES = [
    ('impresso','Impresso'),
    ('tv','TV'),
    ('radio','Rádio'),
    ('social','Redes Sociais'),
    ('site','Site'),
]

class ReportConfig(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE)
    month  = models.DateField(help_text="Escolha um dia qualquer do mês")
    created_at = models.DateTimeField(auto_now_add=True)
    # … outros ajustes por cliente, se precisar …

class ClippingEntry(models.Model):
    report        = models.ForeignKey(ReportConfig, on_delete=models.CASCADE, related_name='entries')
    article       = models.ForeignKey('newsclip.Article', on_delete=models.SET_NULL, null=True)
    coverage_type = models.CharField(max_length=20, choices=COVERAGE_CHOICES)
    media_channel = models.CharField(max_length=20, choices=MEDIA_CHOICES)
    valor_cm      = models.DecimalField("Valoração (cm)", max_digits=7, decimal_places=2, default=0)
    screenshot    = models.ImageField(upload_to='reports/screenshots/', blank=True, null=True)
    # … campos extras de interesse …
