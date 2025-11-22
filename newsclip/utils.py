# newsclip/utils.py

import re
import hashlib
from pathlib import Path
from collections import Counter
from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone as dj_timezone
# from googlesearch import search  # Temporarily disabled - requires distutils (removed in Python 3.14)
from dateutil import parser as date_parser

# Importações adicionadas para SearchVector
from django.contrib.postgres.search import SearchVector
from django.db.models import Value # Para tratar campos potencialmente nulos no SearchVector

from newsclip.models import Article


# —————————————————————————————————————————
# 1) Summary extractivo rápido (NLTK)
# —————————————————————————————————————————

# ATENÇÃO: Execute uma única vez:
# pip install nltk
# python -m nltk.downloader punkt stopwords


def generate_summary(text: str, num_sentences: int = 3) -> str:
    # resumo extractivo simples: pega as N primeiras sentenças
    # Idealmente, este resumo deveria ser do conteúdo do artigo, não do título.
    if not text: # Adicionado para evitar erro se text for None ou vazio
        return ""
    sentences = text.split('.')
    summary = '.'.join(sentences[:num_sentences]).strip()
    if summary and not summary.endswith('.'): # Adicionado para garantir que termina com ponto se não vazio
        summary += '.'
    return summary


# —————————————————————————————————————————
# 2) Busca no Google via GPT + googlesearch
# —————————————————————————————————————————

# —————————————————————————————————————————
# 2) Busca no Google via GPT + googlesearch
# —————————————————————————————————————————

import requests

def search_google_api(query, api_key, cse_id, num_results=10, **kwargs):
    """
    Realiza busca usando a Google Custom Search JSON API.
    """
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        'q': query,
        'key': api_key,
        'cx': cse_id,
        'num': min(num_results, 10), # API limita a 10 por página
        'lr': 'lang_pt',
        **kwargs
    }
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        items = data.get('items', [])
        return [item['link'] for item in items]
    except Exception as e:
        print(f"Erro na Google API: {e}")
        return []

def buscar_com_google(queries: list[str], num_results: int = 10) -> list[str]:
    urls = []
    
    # Verificar se temos chaves de API configuradas
    api_key = getattr(settings, 'GOOGLE_API_KEY', None)
    cse_id = getattr(settings, 'GOOGLE_CSE_ID', None)
    use_api = bool(api_key and cse_id)

    for q in queries:
        try:
            if use_api:
                # Usar API Oficial
                print(f"Buscando via Google API: {q}")
                results = search_google_api(q, api_key, cse_id, num_results=num_results)
                urls.extend(results)
            else:
                # Fallback para Scraping (googlesearch-python)
                print(f"Buscando via Scraping (googlesearch): {q}")
                for url_result in search(q, num_results=num_results, lang="pt"):
                    urls.append(url_result)
                    
        except Exception as e:
            print(f"Erro ao buscar no Google para query '{q}': {e}")
            
    return list(set(urls)) # Remove duplicatas


# —————————————————————————————————————————
# 3) Classificação de tópico simples
# —————————————————————————————————————————

class SimpleTopicClassifier:
    def __init__(self):
        self.topic_keywords = {
            "Política": ["presidente","governo","ministro","senado","câmara","política", "deputado", "lei", "eleição"],
            "Economia": ["economia","inflação","juros","pib","comércio","financeiro", "dólar", "bolsa"],
            "Esportes": ["jogo","time","futebol","campeonato","esportes","olímpico", "atleta", "vitória", "derrota"],
            "Tecnologia": ["tecnologia","startup","inovação","software","hardware","internet", "app", "ia"],
            "Cultura": ["cultura","música","filme","arte","literatura","teatro", "show", "exposição"],
            "Saúde": ["saúde","hospital","vacina","doença","médico","tratamento", "pandemia", "oms"],
            # Adicionar mais tópicos e palavras-chave conforme necessário
        }

    def classify(self, text: str) -> str:
        if not text: # Adicionado para evitar erro se text for None ou vazio
            return "Sem classificação"
        text_low = text.lower()
        scores = {
            topic: sum(text_low.count(kw) for kw in kws)
            for topic, kws in self.topic_keywords.items()
        }
        # Verifica se há algum score maior que zero para evitar erro com max() em lista vazia ou só com zeros
        if not any(s > 0 for s in scores.values()):
            return "Sem classificação"

        best, val = max(scores.items(), key=lambda x: x[1])
        return best # Removido 'if val > 0' pois já verificado acima

_topic_clf = SimpleTopicClassifier()


# —————————————————————————————————————————
# 4) Salvamento de artigos no banco
# —————————————————————————————————————————

def save_article(client, title, url, raw_date, source, content_text=None):
    """
    Salva um artigo no banco de dados e calcula seu search_vector.
    """
    dt = None
    if raw_date:
        try:
            parsed = date_parser.parse(str(raw_date))
            dt = parsed if parsed.tzinfo else dj_timezone.make_aware(
                parsed, dj_timezone.get_current_timezone()
            )
        except Exception as e:
            print(f"Erro ao parsear data '{raw_date}' para o título '{title[:50]}...': {e}. Usando None.")
            dt = None

    processed_title = (title or "")[:Article._meta.get_field('title').max_length]
    processed_source = (source or "")[:Article._meta.get_field('source').max_length]
    
    summary_text = generate_summary(content_text if content_text else processed_title)
    topic_classification = _topic_clf.classify(processed_title) # _topic_clf deve estar definido neste arquivo

    article_instance = None
    try:
        article_instance = Article.objects.create(
            client=client,
            title=processed_title,
            url=url,
            published_at=dt,  # <--- CORREÇÃO APLICADA AQUI
            source=processed_source,
            summary=summary_text,
            topic=topic_classification,
            content=content_text if content_text else "",
        )
        # print(f"Artigo CRIADO: {article_instance.title_truncado}") # title_truncado é uma property no modelo Article

        # Lógica do SearchVector (adaptada para SQLite como no update_vectors.py)
        title_for_vector = article_instance.title or ""
        summary_for_vector = article_instance.summary or ""
        content_for_vector = article_instance.content or ""

        # Para SQLite, atribuímos a string concatenada.
        # Para PostgreSQL (produção), você usaria a forma com SearchVector(...) com pesos/config.
        # Considere uma lógica condicional baseada no settings.DATABASES['default']['ENGINE'] se necessário.
        combined_text_for_fts = f"{title_for_vector} {summary_for_vector} {content_for_vector}"
        article_instance.search_vector = combined_text_for_fts
        
        article_instance.save(update_fields=['search_vector'])
        # print(f"Search vector atualizado para: {article_instance.title_truncado}")

    except IntegrityError:
        # print(f"Artigo JÁ EXISTE (URL): {url}")
        pass
    except Exception as e:
        print(f"ERRO GERAL ao salvar artigo '{processed_title}' ({url}): {e}")

    return article_instance


