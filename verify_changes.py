import os
import django
import sys

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from newsclip.models import Client, Article
from django.db.utils import IntegrityError

def verify_signal():
    print("--- Verificando Signal de Atualização de Vetor ---")
    try:
        # Criar um cliente de teste
        client, _ = Client.objects.get_or_create(name="Cliente Teste Verificacao", defaults={'keywords': 'teste'})
        
        # Criar um artigo
        title = "Título de Teste para Signal"
        content = "Conteúdo relevante para busca"
        url = "http://exemplo.com/teste-signal-verificacao"
        
        # Limpar se já existir
        Article.objects.filter(url=url).delete()
        
        article = Article.objects.create(
            client=client,
            title=title,
            content=content,
            url=url
        )
        
        # Recarregar do banco para garantir que pegamos o valor salvo
        article.refresh_from_db()
        
        expected_vector = f"{title}  {content}" # Summary é vazio/None, então vira ''
        
        print(f"Vetor no banco: '{article.search_vector}'")
        
        if article.search_vector and title in article.search_vector and content in article.search_vector:
            print("✅ SUCESSO: O vetor de busca foi atualizado automaticamente pelo Signal.")
        else:
            print("❌ FALHA: O vetor de busca não corresponde ao esperado.")
            
    except Exception as e:
        print(f"❌ ERRO durante o teste do signal: {e}")

def verify_task_import():
    print("\n--- Verificando Importação da Task ---")
    try:
        from newsclip.tasks import fetch_news_task
        print("✅ SUCESSO: A task 'fetch_news_task' foi importada corretamente.")
    except ImportError as e:
        print(f"❌ FALHA: Não foi possível importar a task: {e}")

if __name__ == "__main__":
    verify_signal()
    verify_task_import()
