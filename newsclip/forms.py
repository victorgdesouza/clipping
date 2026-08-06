from django import forms
from urllib.parse import urlsplit

from .models import Client


class ReportForm(forms.Form):
    REPORT_TYPE_CHOICES = [
        ("custom", "Personalizado"),
        ("comparative", "Comparativo"),
    ]
    FORMAT_CHOICES = [
        ("pdf", "PDF"),
        ("xlsx", "Excel (.xlsx)"),
        ("csv", "CSV"),
    ]

    report_type = forms.ChoiceField(choices=REPORT_TYPE_CHOICES, label="Tipo de relatorio")
    start_date = forms.DateField(required=False, label="Data inicial", widget=forms.DateInput(attrs={"type": "date"}))
    end_date = forms.DateField(required=False, label="Data final", widget=forms.DateInput(attrs={"type": "date"}))
    comparison_start_date = forms.DateField(required=False, label="Inicio do segundo periodo", widget=forms.DateInput(attrs={"type": "date"}))
    comparison_end_date = forms.DateField(required=False, label="Fim do segundo periodo", widget=forms.DateInput(attrs={"type": "date"}))
    out_format = forms.ChoiceField(choices=FORMAT_CHOICES, label="Formato")

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        report_type = cleaned_data.get("report_type")

        if not start_date or not end_date:
            raise forms.ValidationError("Informe a data inicial e a data final do primeiro periodo.")
        if end_date < start_date:
            self.add_error("end_date", "A data final deve ser igual ou posterior a data inicial.")

        if report_type == "comparative":
            comparison_start = cleaned_data.get("comparison_start_date")
            comparison_end = cleaned_data.get("comparison_end_date")
            if not comparison_start or not comparison_end:
                raise forms.ValidationError("Informe as duas datas do segundo periodo.")
            elif comparison_end < comparison_start:
                self.add_error("comparison_end_date", "O fim do segundo periodo deve ser igual ou posterior ao inicio.")
        return cleaned_data


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
