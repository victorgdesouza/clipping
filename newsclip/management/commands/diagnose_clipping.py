from django.core.management.base import BaseCommand, CommandError

from newsclip.diagnostics import build_clipping_diagnostic


class Command(BaseCommand):
    help = "Diagnostica cobertura, relevancia e fontes para um cliente."

    def add_arguments(self, parser):
        parser.add_argument("--client", default="Fabio Candido", help="Trecho do nome do cliente")
        parser.add_argument("--start", default="2026-04-01", help="Data inicial YYYY-MM-DD")
        parser.add_argument("--end", default="2026-07-06", help="Data final YYYY-MM-DD")

    def handle(self, *args, **options):
        from datetime import date

        start = date.fromisoformat(options["start"])
        end = date.fromisoformat(options["end"])
        client, output = build_clipping_diagnostic(options["client"], start, end)
        if not client:
            raise CommandError(f"Cliente nao encontrado: {options['client']}")
        self.stdout.write(output)
