from django.core.management.base import BaseCommand, CommandError

from newsclip.models import Client
from newsclip.utils import append_unique_terms, revalidate_pending_articles_for_client, split_terms


class Command(BaseCommand):
    help = "Revalida noticias pendentes/rejeitadas de um cliente apos ajuste de identidade/contexto."

    def add_arguments(self, parser):
        parser.add_argument("--client-id", type=int, required=True, help="ID exato do cliente")
        parser.add_argument(
            "--status",
            action="append",
            choices=["REVIEW", "REJECTED"],
            help="Status a revalidar. Pode repetir. Padrao: REVIEW e REJECTED.",
        )
        parser.add_argument(
            "--add-name-variation",
            action="append",
            default=[],
            help="Variação de nome/identidade forte a adicionar antes de revalidar. Pode repetir.",
        )
        parser.add_argument("--limit", type=int, help="Limite opcional de artigos a processar")
        parser.add_argument("--dry-run", action="store_true", help="Simula sem gravar alteracoes")

    def handle(self, *args, **options):
        client = Client.objects.filter(pk=options["client_id"]).first()
        if not client:
            raise CommandError(f"Cliente {options['client_id']} nao encontrado.")

        dry_run = options["dry_run"]
        variations = []
        for raw in options.get("add_name_variation") or []:
            variations.extend(split_terms(raw))

        added = []
        if variations:
            updated_value, added = append_unique_terms(client.name_variations, variations)
            if not dry_run and added:
                client.name_variations = updated_value
                client.save(update_fields=["name_variations"])
            elif dry_run:
                client.name_variations = updated_value

        statuses = options.get("status") or ["REVIEW", "REJECTED"]
        stats = revalidate_pending_articles_for_client(
            client,
            statuses=statuses,
            limit=options.get("limit"),
            persist=not dry_run,
        )

        mode = "DRY-RUN" if dry_run else "APLICADO"
        self.stdout.write(f"{mode}: {client.name} [id:{client.pk}]")
        if variations:
            self.stdout.write(f"Variacoes novas: {', '.join(added) if added else 'nenhuma'}")
        self.stdout.write(f"Status revalidados: {', '.join(statuses)}")
        self.stdout.write(f"Processados: {stats['processed']}")
        self.stdout.write(f"Alterados: {stats['changed']}")
        self.stdout.write(f"Promovidos para ACCEPTED: {stats['promoted']}")
        self.stdout.write(f"Resultado calculado: ACCEPTED={stats['accepted']} REVIEW={stats['review']} REJECTED={stats['rejected']}")
