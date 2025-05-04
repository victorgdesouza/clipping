# newsclip/utils.py

import re
import hashlib
from collections import Counter
import dateutil.parser
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError
from django.utils import timezone as dj_timezone

from huggingface_hub import hf_hub_download
from gpt4all import GPT4All
from googlesearch import search

from newsclip.models import Article


# —————————————————————————————————————————
# 1) Carregamento do modelo GPT4All via Hugging Face Hub
# —————————————————————————————————————————

# Identificação do repositório e nome do arquivo .gguf no HF Hub
HF_REPO_ID  = "maddes8cht/nomic-ai-gpt4all-falcon-gguf"
HF_FILENAME = "nomic-ai-gpt4all-falcon-gguf.gguf"

# hf_hub_download baixa (ou retorna de cache) o .gguf em ~/.cache/huggingface/hub/
MODEL_PATH = hf_hub_download(
    repo_id=HF_REPO_ID,
    filename=HF_FILENAME
)

# Inicializa o GPT4All apontando para esse arquivo
gpt = GPT4All(
    model_name=HF_FILENAME,
    model_path=str(MODEL_PATH),
    allow_download=False,  # nunca tentar baixar de outro lugar
    verbose=False
)


# —————————————————————————————————————————
# 2) Geração de queries otimizadas + busca Google
# —————————————————————————————————————————

def gerar_consultas_com_gpt4all(keywords: list[str], max_queries: int = 5) -> list[str]:
    """
    Gera até `max_queries` strings de busca otimizadas pelo GPT4All,
    incluindo foco em Instagram, LinkedIn, YouTube e portais de jornais.
    """
    prompt = (
        f"Você é um buscador de notícias. Gere até {max_queries} consultas Google "
        f"otimizadas para encontrar notícias sobre estas palavras-chave: {keywords}. "
        "Inclua termos como site:instagram.com, site:linkedin.com, site:youtube.com "
        "e portais de jornais impressos."
    )
    resp = gpt.generate(prompt)
    # Divide em linhas e filtra vazias
    queries = [linha.strip() for linha in resp.splitlines() if linha.strip()]
    return queries[:max_queries]

def buscar_com_google(queries: list[str], num_results: int = 20) -> list[str]:
    # gera chave a partir das queries
    key = "llm_urls:" + hashlib.md5("|".join(queries).encode("utf-8")).hexdigest()
    cached = cache.get(key)
    if cached is not None:
        return cached

    urls = []
    for q in queries:
        try:
            for url in search(q, num_results=num_results, lang="pt"):
                urls.append(url)
        except Exception:
            continue
    # dedupe mantendo ordem
    urls = list(dict.fromkeys(urls))
    # armazena no cache por 1 dia (86400s)
    cache.set(key, urls, timeout=86400)
    return urls


# —————————————————————————————————————————
# 3) Resumo simples e classificação de tópico
# —————————————————————————————————————————

# Stopwords em pt-BR
STOPWORDS = {
    "de","a","o","que","e","do","da","em","um","para",
    "é","com","não","uma","os","no","se","na","por","mais",
    "as","dos","como","mas","foi","ao","ele","das","tem",
    "à","seu","sua","ou","ser","quando","muito","há","nos",
    "já","está","eu","também","só","pelo","pela","até"
}

def generate_summary(text: str, num_sentences: int = 3) -> str:
    """
    Extrai as `num_sentences` sentenças mais importantes de `text`
    com base na frequência de palavras (excluindo stopwords).
    """
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    if len(sentences) <= num_sentences:
        return text

    words = re.findall(r'\w+', text.lower())
    freq = Counter(w for w in words if w not in STOPWORDS)

    scored = []
    for sent in sentences:
        s_words = re.findall(r'\w+', sent.lower())
        score = sum(freq[w] for w in s_words)
        scored.append((score, sent))

    top = sorted(scored, key=lambda x: x[0], reverse=True)[:num_sentences]
    top_sents = {s for _, s in top}
    # Mantém a ordem original
    summary = [s for s in sentences if s in top_sents]
    return " ".join(summary)

class SimpleTopicClassifier:
    """
    Classificador simples baseado em dicionário de palavras-chave.
    """
    def __init__(self):
        self.topic_keywords = {
            "Política": ["presidente","governo","ministro","senado","câmara","política"],
            "Economia": ["economia","inflação","juros","pib","comércio","financeiro"],
            "Esportes": ["jogo","time","futebol","campeonato","esportes","olímpico"],
            "Tecnologia": ["tecnologia","startup","inovação","software","hardware","internet"],
            "Cultura": ["cultura","música","filme","arte","literatura","teatro"],
            "Saúde": ["saúde","hospital","vacina","doença","médico","tratamento"],
        }

    def classify(self, text: str) -> str:
        text_low = text.lower()
        scores = {topic: sum(text_low.count(kw) for kw in kws)
                  for topic, kws in self.topic_keywords.items()}
        best, val = max(scores.items(), key=lambda x: x[1])
        return best if val > 0 else "Sem classificação"

_topic_clf = SimpleTopicClassifier()

# —————————————————————————————————————————
# 4) Salvamento de artigos no banco
# —————————————————————————————————————————

def save_article(client, title, url, raw_date, source):
    """
    Cria um Article (evita duplicatas), converte raw_date,
    gera summary e topic automaticamente.
    """
    dt = None
    if raw_date:
        try:
            parsed = dateutil.parser.parse(raw_date)
            if getattr(parsed, "tzinfo", None) is None:
                dt = dj_timezone.make_aware(parsed, dj_timezone.get_current_timezone())
            else:
                dt = parsed
        except Exception:
            dt = None

    try:
        Article.objects.create(
            client=client,
            title=title[:300],
            url=url,
            published_at=dt,
            source=(source or "")[:200],
            summary=generate_summary(title),
            topic=_topic_clf.classify(title),
        )
    except IntegrityError:
        # já existia → ignora
        pass
