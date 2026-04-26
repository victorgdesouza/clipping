from django import forms

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
        fields = ["name", "keywords", "domains", "instagram", "x", "youtube"]
        widgets = {
            "keywords": forms.Textarea(
                attrs={
                    "rows": 2,
                    "class": "auto-expand",
                    "placeholder": "Ex: termo1, termo2...",
                }
            ),
            "domains": forms.Textarea(
                attrs={
                    "rows": 2,
                    "class": "auto-expand",
                    "placeholder": "Ex: g1.globo.com, uol.com.br...",
                }
            ),
            "instagram": forms.TextInput(attrs={"placeholder": "@usuario"}),
            "x": forms.TextInput(attrs={"placeholder": "@usuario"}),
            "youtube": forms.TextInput(attrs={"placeholder": "@canal"}),
        }
        help_texts = {
            "keywords": "Separe os termos por virgula.",
            "domains": "Separe os dominios por virgula.",
            "instagram": "Opcional. Use o perfil publico do cliente.",
            "x": "Opcional. Use o perfil publico do cliente.",
            "youtube": "Opcional. Use o canal ou usuario publico do cliente.",
        }
