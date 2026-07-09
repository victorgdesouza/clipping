from django import forms
from urllib.parse import urlsplit

from .models import Client


class ReportForm(forms.Form):
    DAYS_CHOICES = [
        ("15", "Ultimos 15 dias"),
        ("30", "Ultimos 30 dias"),
        ("60", "Ultimos 60 dias"),
        ("90", "Ultimos 90 dias"),
        ("all", "Relatorio completo"),
    ]
    FORMAT_CHOICES = [
        ("pdf", "PDF"),
        ("xlsx", "Excel (.xlsx)"),
        ("csv", "CSV"),
    ]

    days = forms.ChoiceField(choices=DAYS_CHOICES, label="Intervalo")
    out_format = forms.ChoiceField(choices=FORMAT_CHOICES, label="Formato")


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = [
            "name",
            "name_variations",
            "context_terms",
            "keywords",
            "excluded_keywords",
            "domains",
            "instagram",
            "x",
            "youtube",
        ]
        widgets = {
            "name_variations": forms.Textarea(
                attrs={
                    "rows": 2,
                    "class": "auto-expand",
                    "placeholder": "Ex: nome abreviado, apelido publico, nome com cargo, @perfiloficial",
                }
            ),
            "context_terms": forms.Textarea(
                attrs={
                    "rows": 2,
                    "class": "auto-expand",
                    "placeholder": "Ex: cidade, setor de atuacao, cargo, evento, produto, tema relacionado...",
                }
            ),
            "keywords": forms.Textarea(
                attrs={
                    "rows": 2,
                    "class": "auto-expand",
                    "placeholder": "Opcional. Use apenas termos realmente relacionados ao cliente.",
                }
            ),
            "excluded_keywords": forms.Textarea(
                attrs={
                    "rows": 2,
                    "class": "auto-expand",
                    "placeholder": "Ex: Rio Preto da Eva, termo indesejado...",
                }
            ),
            "domains": forms.Textarea(
                attrs={
                    "rows": 2,
                    "class": "auto-expand",
                    "placeholder": "Ex: arenacp.com.br ou https://arenacp.com.br/carlinhos-pinheiro/",
                }
            ),
            "instagram": forms.TextInput(attrs={"placeholder": "@usuario"}),
            "x": forms.TextInput(attrs={"placeholder": "@usuario"}),
            "youtube": forms.TextInput(attrs={"placeholder": "@canal"}),
        }
        help_texts = {
            "name_variations": "Como o cliente pode aparecer na noticia: abreviacoes, nome oficial, apelidos publicos, cargos ou perfis oficiais.",
            "context_terms": "Assuntos que ajudam a confirmar relevancia. Sozinhos nao aprovam; servem para diferenciar noticias parecidas.",
            "keywords": "Termos extras de apoio. Use para temas relacionados, nao para palavras muito genericas.",
            "excluded_keywords": "Termos que indicam que a noticia nao pertence ao cliente, como cidade, pessoa ou assunto homonimo.",
            "domains": "Aceita dominio ou URL completa. URLs sao normalizadas para host e caminho opcional.",
            "instagram": "Opcional. Use o perfil publico do cliente.",
            "x": "Opcional. Use o perfil publico do cliente.",
            "youtube": "Opcional. Canais informados sao fontes adicionais; a busca ampla usa o nome e as palavras-chave do cliente.",
        }

    def clean_domains(self):
        raw_value = self.cleaned_data.get("domains", "")
        normalized_items = []
        seen = set()
        for item in raw_value.replace("\n", ",").split(","):
            value = item.strip()
            if not value:
                continue
            parsed = urlsplit(value if "://" in value else f"https://{value}")
            host = (parsed.hostname or value).casefold()
            if host.startswith("www."):
                host = host[4:]
            path = (parsed.path or "").strip()
            if path and path != "/":
                path = "/" + path.strip("/")
            normalized = f"{host}{path}"
            if normalized and normalized not in seen:
                normalized_items.append(normalized)
                seen.add(normalized)
        return ", ".join(normalized_items)
