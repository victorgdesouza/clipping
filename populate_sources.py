import os
import django
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from newsclip.models import Source
from newsclip.management.commands.fetch_news import ALL_RSS_FEEDS_FLAT, SCRAPE_SITES

def populate_sources():
    print("--- Migrando Fontes para o Banco de Dados ---")
    
    # 1. RSS Feeds
    count_rss = 0
    for url in ALL_RSS_FEEDS_FLAT:
        # Tenta extrair um nome amigável da URL
        try:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc.replace("www.", "")
            name = f"{domain} (RSS)"
        except:
            name = "Fonte RSS Desconhecida"

        obj, created = Source.objects.get_or_create(
            url=url,
            defaults={
                'name': name,
                'source_type': 'RSS',
                'is_active': True
            }
        )
        if created:
            count_rss += 1
            print(f"Criado RSS: {name}")
        else:
            print(f"Já existe RSS: {name}")

    # 2. Scrape Sites
    count_scrape = 0
    for site in SCRAPE_SITES:
        url = site['url']
        try:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc.replace("www.", "")
            name = f"{domain} (Scrape)"
        except:
            name = "Fonte Scrape Desconhecida"
            
        obj, created = Source.objects.get_or_create(
            url=url,
            defaults={
                'name': name,
                'source_type': 'SCRAPE',
                'is_active': True,
                'title_selector': site.get('title_selector'),
                'link_selector': site.get('link_selector'),
                'date_selector': site.get('date_selector'),
            }
        )
        if created:
            count_scrape += 1
            print(f"Criado Scrape: {name}")
        else:
            print(f"Já existe Scrape: {name}")

    print(f"\nConcluído! {count_rss} feeds RSS e {count_scrape} sites de scrape adicionados.")

if __name__ == "__main__":
    populate_sources()
