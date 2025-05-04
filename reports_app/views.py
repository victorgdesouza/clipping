from django.views.generic import TemplateView
from django.shortcuts import get_object_or_404
from newsclip.models import Client, Article
from .models import ReportConfig, ClippingEntry, COVERAGE_CHOICES  # ← aqui
from django.utils import timezone
from django.db.models import Count, Sum
from datetime import date


class MonthlyReportView(TemplateView):
    template_name = 'reports_app/monthly.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        client   = get_object_or_404(Client, pk=kwargs['client_id'])
        year, mo = kwargs['year'], kwargs['month']
        # filtra clippings do mês e do cliente
        config, _ = ReportConfig.objects.get_or_create(client=client,
                               month=date(year, mo, 1))
        entries = ClippingEntry.objects.filter(report=config)

        # Overview
        ctx['totals'] = {
            c: entries.filter(coverage_type=c).count()
            for c,_ in COVERAGE_CHOICES
        }
        ctx['by_media'] = entries.values('media_channel').annotate(n=Count('id'))
        ctx['valor_total'] = entries.aggregate(v=Sum('valor_cm'))['v'] or 0

        # Tabela completa
        ctx['entries'] = entries.select_related('article')
        return ctx

