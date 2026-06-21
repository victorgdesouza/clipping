# newsclip/management/commands/generate_report.py

import html
import pathlib

import pandas as pd
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.text import slugify
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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
                    f"{client.name}: relatório Excel gerado -> {output_path}"
                ))
            else:  # CSV
                df.to_csv(output_path, index=False, encoding="utf-8")
                self.stdout.write(self.style.SUCCESS(
                    f"{client.name}: relatório CSV gerado -> {output_path}"
                ))
            return

        # === PDF (ReportLab, sem binario externo) ===
        styles = getSampleStyleSheet()
        cell_style = ParagraphStyle(
            "ReportCell",
            parent=styles["BodyText"],
            fontSize=7,
            leading=9,
            splitLongWords=True,
        )
        header_style = ParagraphStyle(
            "ReportHeader",
            parent=cell_style,
            textColor=colors.white,
            fontName="Helvetica-Bold",
        )
        document = SimpleDocTemplate(
            str(output_path),
            pagesize=landscape(A4),
            rightMargin=1 * cm,
            leftMargin=1 * cm,
            topMargin=1 * cm,
            bottomMargin=1 * cm,
            title=f"Relatorio de clipping - {client.name}",
        )
        story = [
            Paragraph(f"Relatorio de clipping - {html.escape(client.name)}", styles["Title"]),
            Paragraph(
                "Periodo: " + ("Completo" if days is None else f"Ultimos {days} dias"),
                styles["BodyText"],
            ),
            Paragraph(f"Gerado em: {now.strftime('%d/%m/%Y %H:%M')}", styles["BodyText"]),
            Spacer(1, 0.4 * cm),
        ]
        table_data = [
            [Paragraph(label, header_style) for label in ("Titulo", "Data", "Fonte", "Link")]
        ]
        for row in data:
            table_data.append(
                [
                    Paragraph(html.escape(str(row["Título"])), cell_style),
                    Paragraph(html.escape(str(row["Data"])), cell_style),
                    Paragraph(html.escape(str(row["Fonte"])), cell_style),
                    Paragraph(html.escape(str(row["Link"])), cell_style),
                ]
            )

        table = Table(
            table_data,
            colWidths=[8.5 * cm, 3.2 * cm, 4.2 * cm, 10 * cm],
            repeatRows=1,
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2457A6")),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#B8C2CC")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F7FA")]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(table)
        document.build(story)
        self.stdout.write(self.style.SUCCESS(
            f"{client.name}: relatório PDF gerado -> {output_path}"
        ))






