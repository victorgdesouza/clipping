from django.core.management.base import BaseCommand, CommandError

from municipal_dashboard.seeding import sync_catalog


class Command(BaseCommand):
    help = "Sincroniza dimensões, eixos, indicadores e seeds municipais oficiais."

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-seeds",
            action="store_true",
            help="Sincroniza somente o catálogo, sem criar as medições oficiais iniciais.",
        )

    def handle(self, *args, **options):
        try:
            summary = sync_catalog(include_seeds=not options["no_seeds"])
        except Exception as error:
            raise CommandError(f"Falha ao sincronizar o catálogo: {error}") from error

        labels = {
            "dimensions": "Dimensões",
            "axes": "Eixos",
            "indicators": "Indicadores",
            "measurements": "Medições oficiais",
        }
        for key, label in labels.items():
            counts = summary[key]
            self.stdout.write(
                f"{label}: {counts['created']} criados, "
                f"{counts['updated']} atualizados, "
                f"{counts['unchanged']} inalterados."
            )
        self.stdout.write(self.style.SUCCESS("Catálogo municipal sincronizado."))
