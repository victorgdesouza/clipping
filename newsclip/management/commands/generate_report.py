# newsclip/management/commands/generate_report.py

import os
import pathlib

import pandas as pd
import pdfkit
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.management.base import BaseCommand
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.text import slugify

from newsclip.models import Client, Article


class Command(BaseCommand):
    help = "Gera relatório (PDF/Excel/CSV) de notícias para um cliente num intervalo arbitrário"

    def add_arguments(self, parser):
        parser.add_argument(
            "--client_id", type=int, required=True,
            help="ID do cliente"
        )
        parser.add_argument(
            "--days", type=str, required=True,
            help="Intervalo em dias (número) ou 'all' para relatório completo"
        )
        parser.add_argument(
            "--format", choices=["pdf", "xlsx", "csv"], required=True,
            help="Formato de saída"
        )

    def handle(self, *args, **options):
        client_id  = options["client_id"]
        days_opt   = options["days"]    # string: "15","30",… ou "all"
        out_format = options["format"]

        # DEBUG opcional
        self.stdout.write(f"DEBUG: gerar_report client={client_id}, days={days_opt}, format={out_format}")

        # interpreta days_opt
        days = None if days_opt.lower() == "all" else int(days_opt)

        # carrega cliente
        try:
            client = Client.objects.get(pk=client_id)
        except Client.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"Cliente {client_id} não encontrado."))
            return

        # monta queryset de artigos
        now = timezone.now()
        if days is not None:
            since = now - relativedelta(days=days)
            qs = Article.objects.filter(
                client=client,
                published_at__gte=since,
                published_at__lte=now
            ).order_by("published_at")
        else:
            qs = Article.objects.filter(client=client).order_by("published_at")

        if not qs.exists():
            msg = "nenhum artigo neste período." if days is not None else "nenhum artigo cadastrado."
            self.stdout.write(self.style.WARNING(f"{client.name}: {msg}"))
            return

        # monta DataFrame
        data = []
        for art in qs:
            data.append({
                "Título": art.title,
                "Data": art.published_at.astimezone(
                    timezone.get_current_timezone()
                ).strftime("%d/%m/%Y %H:%M"),
                "Link": art.url,
                "Fonte": art.source
            })
        df = pd.DataFrame(data)

        # prepara diretório
        rep_dir = pathlib.Path(settings.MEDIA_ROOT) / "reports"
        rep_dir.mkdir(parents=True, exist_ok=True)

        # slug, data, label e versão
        slug     = slugify(client.name)               # ex: "luiz-carlos-motta"
        date_str = now.strftime("%d%m%Y")             # ex: "08052025"
        label    = f"{days}d" if days is not None else "all"  # ex: "15d" ou "all"

        # detecta versões já existentes
        existing = list(rep_dir.glob(f"relatorio_{slug}_{date_str}_v*_{label}.*"))
        vers = []
        for p in existing:
            parts = p.stem.split("_")
            for part in parts:
                if part.startswith("v") and part[1:].isdigit():
                    vers.append(int(part[1:]))
        v = max(vers) + 1 if vers else 1

        # monta nome final e caminho
        filename    = f"relatorio_{slug}_{date_str}_v{v}_{label}.{out_format}"
        output_path = rep_dir / filename

        # === CSV / XLSX ===
        if out_format in ("csv", "xlsx"):
            if out_format == "xlsx":
                with pd.ExcelWriter(output_path, engine="xlsxwriter") as writer:
                    df.to_excel(writer, index=False, sheet_name="Artigos")
                    workbook  = writer.book
                    worksheet = writer.sheets["Artigos"]
                    max_row, max_col = df.shape
                    worksheet.add_table(
                        0, 0, max_row, max_col - 1,
                        {
                            "columns": [{"header": h} for h in df.columns],
                            "style": "Table Style Medium 9",
                            "autofilter": True
                        }
                    )
                    for i, col in enumerate(df.columns):
                        width = max(df[col].astype(str).map(len).max(), len(col)) + 2
                        worksheet.set_column(i, i, width)
                self.stdout.write(self.style.SUCCESS(
                    f"{client.name}: relatório Excel gerado → {output_path}"
                ))
            else:  # CSV
                df.to_csv(output_path, index=False, encoding="utf-8")
                self.stdout.write(self.style.SUCCESS(
                    f"{client.name}: relatório CSV gerado → {output_path}"
                ))
            return

        # === PDF (wkhtmltopdf) ===
        bin_path = getattr(settings, "WKHTMLTOPDF_CMD", None)
        if not bin_path or not os.path.isfile(bin_path):
            import shutil
            bin_path = shutil.which("wkhtmltopdf")
            if not bin_path:
                self.stderr.write(self.style.ERROR(
                    "❌ wkhtmltopdf não encontrado. Configure WKHTMLTOPDF_CMD."
                ))
                return

        html = render_to_string("report_templates/report.html", {
            "client": client,
            "articles": df.to_dict(orient="records"),
            "interval": "Completo" if days is None else f"Últimos {days} dias",
            "generated_at": now,
        })
        config  = pdfkit.configuration(wkhtmltopdf=bin_path)
        options = {
            "encoding":    "UTF-8",
            "page-size":   "A4",
            "margin-top":    "1cm",
            "margin-right":  "1cm",
            "margin-bottom": "1cm",
            "margin-left":   "1cm",
        }
        pdfkit.from_string(
            html,
            str(output_path),
            configuration=config,
            options=options
        )
        self.stdout.write(self.style.SUCCESS(
            f"{client.name}: relatório PDF gerado → {output_path}"
        ))






