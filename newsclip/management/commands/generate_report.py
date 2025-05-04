# newsclip/management/commands/generate_report.py

import os
import pathlib
import pandas as pd
import pdfkit

from django.conf import settings
from django.core.management.base import BaseCommand
from django.template.loader import render_to_string
from django.utils import timezone

from dateutil.relativedelta import relativedelta

from newsclip.models import Client, Article


class Command(BaseCommand):
    help = "Gera relatório (PDF/Excel/CSV) de notícias para um cliente num intervalo arbitrário"

    def add_arguments(self, parser):
        parser.add_argument(
            "--client_id", type=int, required=True,
            help="ID do cliente"
        )
        parser.add_argument(
            "--days", type=int, default=30,
            help="Quantos dias para trás buscar"
        )
        parser.add_argument(
            "--format", choices=["pdf", "xlsx", "csv"], default="pdf",
            help="Formato de saída"
        )

    def handle(self, *args, **options):
        client_id = options["client_id"]
        days = options["days"]
        out_format = options["format"]

        # carrega cliente
        try:
            client = Client.objects.get(pk=client_id)
        except Client.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"Cliente {client_id} não encontrado."))
            return

        # intervalo de datas
        now = timezone.now()
        since = now - relativedelta(days=days)

        # busca artigos
        qs = (
            Article.objects
                   .filter(client=client,
                           published_at__gte=since,
                           published_at__lte=now)
                   .order_by("published_at")
        )
        if not qs.exists():
            self.stdout.write(self.style.WARNING(
                f"{client.name}: nenhum artigo neste período ({days} dias)."
            ))
            return

        # monta DataFrame
        df = pd.DataFrame([{
            "Título": art.title,
            # só dia/mês/ano em DD/MM/YY
            "Data": art.published_at.astimezone(timezone.get_current_timezone())
                                     .strftime("%d/%m/%y"),
            "Link": art.url,
            "Fonte": art.source
        } for art in qs])

        # resumo de keywords
        counts = {}
        for kw in (k.strip().lower() for k in client.keywords.split(",") if k.strip()):
            counts[kw] = df["Título"].str.lower().str.count(rf"\b{kw}\b").sum()

        if counts:
            top_kw, top_count = max(counts.items(), key=lambda x: x[1])
            # CORREÇÃO: Uso de aspas simples dentro de aspas duplas para evitar erro de sintaxe
            summary = f"O assunto mais citado foi \"{top_kw}\" com {top_count} menções."
        else:
            summary = "Sem palavras-chave configuradas para resumo."

        # prepara diretório de saída
        media_root = pathlib.Path(settings.MEDIA_ROOT)
        rep_dir = media_root / "reports"
        rep_dir.mkdir(parents=True, exist_ok=True)

        timestamp = now.strftime("%Y%m%d%H%M%S")
        filename = f"report_{client_id}_{days}d_{timestamp}.{out_format}"
        output_path = rep_dir / filename

        # se for CSV ou XLSX
        if out_format in ("csv", "xlsx"):
            if out_format == "xlsx":
                # use xlsxwriter para formatação avançada
                with pd.ExcelWriter(output_path, engine="xlsxwriter") as writer:
                    df.to_excel(writer, index=False, sheet_name="Artigos")
                    
                    # Acessa o workbook e worksheet
                    workbook = writer.book
                    worksheet = writer.sheets["Artigos"]
                    
                    # cria uma tabela Excel (com estilos)
                    (max_row, max_col) = df.shape
                    worksheet.add_table(
                        0, 0,
                        max_row, max_col - 1,
                        {
                            "columns": [{"header": h} for h in df.columns],
                            "style": "Table Style Medium 9",
                            "autofilter": True
                        }
                    )
                    
                    # ajusta largura das colunas
                    for i, col in enumerate(df.columns):
                        width = max(df[col].astype(str).map(len).max(), len(col)) + 2
                        worksheet.set_column(i, i, width)
                    
                    # aba de sumário
                    summary_df = pd.DataFrame({"Sumário": [summary]})
                    summary_df.to_excel(writer, index=False, sheet_name="Sumário")
                
                self.stdout.write(self.style.SUCCESS(
                    f"{client.name}: relatório Excel gerado → {output_path}"
                ))
            else:  # CSV
                # Adiciona o sumário como comentário no início do arquivo
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(f"# {summary}\n")
                    df.to_csv(f, index=False)
                
                self.stdout.write(self.style.SUCCESS(
                    f"{client.name}: relatório CSV gerado → {output_path}"
                ))
            
            return

        # ===== PDF =====
        # Verifica se o wkhtmltopdf está configurado
        bin_path = getattr(settings, "WKHTMLTOPDF_CMD", None)
        if not bin_path or not os.path.isfile(bin_path):
            # Tenta encontrar o wkhtmltopdf no sistema
            import shutil
            bin_path = shutil.which("wkhtmltopdf")
            if not bin_path:
                self.stderr.write(self.style.ERROR(
                    f"❌ wkhtmltopdf não encontrado. Configure WKHTMLTOPDF_CMD nas settings ou instale o wkhtmltopdf."
                ))
                return

        # renderiza o HTML
        html = render_to_string("report_templates/report.html", {
            "client": client,
            "summary": summary,
            "articles": df.to_dict(orient="records"),
            "interval": f"{days} dias",
            "generated_at": now,
        })

        # Caminho para o CSS
        css_path = pathlib.Path(settings.BASE_DIR) / "templates" / "report_templates" / "report.css"
        if not css_path.exists():
            # Tenta encontrar em STATIC_ROOT
            css_path = pathlib.Path(settings.STATIC_ROOT) / "report_templates" / "report.css"
            if not css_path.exists():
                self.stderr.write(self.style.WARNING(
                    f"⚠️ Arquivo CSS não encontrado em {css_path}. O relatório será gerado sem estilos."
                ))
                css_path = None

        try:
            # gera o PDF
            config = pdfkit.configuration(wkhtmltopdf=bin_path)
            options = {
                'encoding': 'UTF-8',
                'page-size': 'A4',
                'margin-top': '1cm',
                'margin-right': '1cm',
                'margin-bottom': '1cm',
                'margin-left': '1cm',
            }
            
            # Adiciona o CSS se existir
            if css_path:
                pdfkit.from_string(
                    html, 
                    str(output_path),
                    configuration=config,
                    options=options,
                    css=str(css_path)
                )
            else:
                pdfkit.from_string(
                    html, 
                    str(output_path),
                    configuration=config,
                    options=options
                )
            
            self.stdout.write(self.style.SUCCESS(
                f"{client.name}: relatório PDF gerado → {output_path}"
            ))
        except Exception as e:
            self.stderr.write(self.style.ERROR(
                f"❌ Erro ao gerar PDF: {e}"
            ))





