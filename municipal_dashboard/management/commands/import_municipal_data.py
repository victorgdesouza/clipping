from django.core.management.base import BaseCommand, CommandError

from municipal_dashboard.importing import (
    MunicipalCSVImportError,
    import_measurements_csv,
)


class Command(BaseCommand):
    help = "Valida e importa medições municipais de um arquivo CSV."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Caminho do arquivo CSV em UTF-8.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Valida e simula as ações sem gravar no banco.",
        )

    def handle(self, *args, **options):
        try:
            result = import_measurements_csv(
                options["path"],
                dry_run=options["dry_run"],
            )
        except MunicipalCSVImportError as error:
            raise CommandError(str(error)) from error
        except Exception as error:
            raise CommandError(f"Falha ao importar o CSV: {error}") from error

        mode = "SIMULAÇÃO" if result["dry_run"] else "IMPORTAÇÃO"
        self.stdout.write(
            f"{mode}: {result['rows']} linhas válidas; "
            f"{result['created']} criações, "
            f"{result['updated']} atualizações, "
            f"{result['unchanged']} inalteradas."
        )
        if result["dry_run"]:
            self.stdout.write(self.style.WARNING("Nenhuma alteração foi gravada."))
        else:
            self.stdout.write(self.style.SUCCESS("Importação municipal concluída."))
