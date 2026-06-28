import html
from io import BytesIO

import pandas as pd
from dateutil.relativedelta import relativedelta
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.text import slugify
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from newsclip.models import Article, Client, GeneratedReport
from newsclip.utils import deduplicate_articles_for_display, revalidate_accepted_articles_for_client


CONTENT_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


class Command(BaseCommand):
    help = "Gera e armazena no banco um relatorio PDF, Excel ou CSV de um cliente."

    def add_arguments(self, parser):
        parser.add_argument("--client_id", type=int, required=True)
        parser.add_argument("--days", type=str, required=True)
        parser.add_argument("--format", choices=["pdf", "xlsx", "csv"], required=True)
        parser.add_argument("--created_by_id", type=int, required=False)

    def handle(self, *args, **options):
        client = Client.objects.filter(pk=options["client_id"]).first()
        if client is None:
            raise CommandError(f"Cliente {options['client_id']} nao encontrado.")

        days_option = options["days"]
        try:
            days = None if days_option.lower() == "all" else int(days_option)
        except ValueError as exc:
            raise CommandError("O periodo deve ser um numero de dias ou 'all'.") from exc

        now = timezone.now()
        revalidate_accepted_articles_for_client(client)
        articles = Article.objects.filter(client=client, excluded=False, validation_status="ACCEPTED")
        if days is not None:
            articles = articles.filter(
                published_at__gte=now - relativedelta(days=days),
                published_at__lte=now,
            )
        articles = deduplicate_articles_for_display(articles.order_by("published_at", "id"))

        if not articles:
            raise CommandError(f"{client.name}: nenhum artigo disponivel para o periodo.")

        data = [
            {
                "Titulo": article.title,
                "Data": (
                    article.published_at.astimezone(timezone.get_current_timezone()).strftime("%d/%m/%Y %H:%M")
                    if article.published_at
                    else "N/A"
                ),
                "Link": article.url,
                "Fonte": article.source,
            }
            for article in articles
        ]
        dataframe = pd.DataFrame(data)
        output_format = options["format"]
        content = self._build_content(dataframe, data, output_format, client, days, now)

        slug = slugify(client.name)
        date_string = now.strftime("%d%m%Y")
        period_label = f"{days}d" if days is not None else "all"
        prefix = f"relatorio_{slug}_{date_string}_v"
        existing_names = GeneratedReport.objects.filter(
            client=client,
            filename__startswith=prefix,
            filename__contains=f"_{period_label}.",
        ).values_list("filename", flat=True)
        versions = []
        for name in existing_names:
            version_part = name.removeprefix(prefix).split("_", 1)[0]
            if version_part.isdigit():
                versions.append(int(version_part))
        version = max(versions, default=0) + 1
        filename = f"{prefix}{version}_{period_label}.{output_format}"

        report = GeneratedReport.objects.create(
            client=client,
            created_by_id=options.get("created_by_id"),
            filename=filename,
            format=output_format,
            period_label=period_label,
            content_type=CONTENT_TYPES[output_format],
            content=content,
            size=len(content),
        )
        self.stdout.write(self.style.SUCCESS(f"Relatorio armazenado: {report.filename} ({report.size} bytes)"))

    def _build_content(self, dataframe, data, output_format, client, days, now):
        output = BytesIO()
        if output_format == "csv":
            return dataframe.to_csv(index=False).encode("utf-8-sig")

        if output_format == "xlsx":
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                dataframe.to_excel(writer, index=False, sheet_name="Artigos")
                worksheet = writer.sheets["Artigos"]
                max_row, max_col = dataframe.shape
                worksheet.add_table(
                    0,
                    0,
                    max_row,
                    max_col - 1,
                    {
                        "columns": [{"header": heading} for heading in dataframe.columns],
                        "style": "Table Style Medium 9",
                        "autofilter": True,
                    },
                )
                for index, column in enumerate(dataframe.columns):
                    width = max(dataframe[column].astype(str).map(len).max(), len(column)) + 2
                    worksheet.set_column(index, index, min(width, 80))
            return output.getvalue()

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
            output,
            pagesize=landscape(A4),
            rightMargin=1 * cm,
            leftMargin=1 * cm,
            topMargin=1 * cm,
            bottomMargin=1 * cm,
            title=f"Relatorio de clipping - {client.name}",
        )
        story = [
            Paragraph(f"Relatorio de clipping - {html.escape(client.name)}", styles["Title"]),
            Paragraph("Periodo: " + ("Completo" if days is None else f"Ultimos {days} dias"), styles["BodyText"]),
            Paragraph(f"Gerado em: {now.strftime('%d/%m/%Y %H:%M')}", styles["BodyText"]),
            Spacer(1, 0.4 * cm),
        ]
        table_data = [[Paragraph(label, header_style) for label in ("Titulo", "Data", "Fonte", "Link")]]
        for row in data:
            url = html.escape(str(row["Link"]), quote=True)
            table_data.append(
                [
                    Paragraph(html.escape(str(row["Titulo"])), cell_style),
                    Paragraph(html.escape(str(row["Data"])), cell_style),
                    Paragraph(html.escape(str(row["Fonte"])), cell_style),
                    Paragraph(f'<link href="{url}">Abrir materia</link>', cell_style),
                ]
            )
        table = Table(table_data, colWidths=[8.5 * cm, 3.2 * cm, 4.2 * cm, 10 * cm], repeatRows=1)
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
        return output.getvalue()
