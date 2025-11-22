from django import forms

class ReportForm(forms.Form):
    DAYS_CHOICES = [
        ('15', "Últimos 15 dias"),
        ('30', "Últimos 30 dias"),
        ('60', "Últimos 60 dias"),
        ('90', "Últimos 90 dias"),
        ('all', "Relatório Completo"),
    ]
    FORMAT_CHOICES = [
        ("pdf", "PDF"),
        ("xlsx", "Excel (.xlsx)"),
        ("csv", "CSV"),
    ]
    days = forms.ChoiceField(choices=DAYS_CHOICES, label="Intervalo")
    out_format = forms.ChoiceField(choices=FORMAT_CHOICES, label="Formato")