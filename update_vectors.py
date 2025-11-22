# update_vectors.py

import os
import django

# 1. Configurar o ambiente do Django PRIMEIRO
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
try:
    django.setup()
except Exception as e:
    print(f"ERRO ao executar django.setup(): {e}")
    print("Verifique se a variável DJANGO_SETTINGS_MODULE ('core.settings') está correta.")
    exit()

# 2. AGORA, importe os modelos e outras partes do Django
from newsclip.models import Article
# Não precisaremos de SearchVector ou Value aqui se atribuirmos string diretamente


def update_existing_article_search_vectors():
    """
    Atualiza o campo search_vector para todos os artigos existentes no banco de dados,
    atribuindo uma string concatenada para compatibilidade com SQLite FTS.
    """
    print("DEBUG: Dentro de update_existing_article_search_vectors().")
    print("Iniciando a atualização dos search_vectors para artigos existentes (atribuição de string para SQLite)...")
    
    batch_size = 50 
    articles_processed_successfully = 0
    
    try:
        total_articles = Article.objects.count()
    except Exception as e:
        print(f"ERRO ao contar artigos: {e}")
        print("Verifique se as migrações do banco de dados estão aplicadas e se o banco está acessível.")
        return

    if total_articles == 0:
        print("Nenhum artigo encontrado no banco de dados para atualizar.")
        return

    print(f"Total de artigos para atualizar: {total_articles}")

    for i in range(0, total_articles, batch_size):
        articles_batch = Article.objects.all().order_by('pk')[i:i+batch_size]
        
        if not articles_batch:
            continue

        print(f"\nProcessando lote de artigos: IDs de aprox. {articles_batch[0].pk} até {articles_batch[len(articles_batch)-1].pk}")

        for article_to_save in articles_batch:
            title_val = article_to_save.title if article_to_save.title is not None else ''
            summary_val = article_to_save.summary if article_to_save.summary is not None else ''
            content_val = article_to_save.content if article_to_save.content is not None else ''

            try:
                # Para SQLite, vamos concatenar os campos em uma única string
                # e atribuir essa string diretamente ao SearchVectorField.
                # Django deve lidar com a indexação FTS dessa string.
                combined_text_for_fts = f"{title_val} {summary_val} {content_val}"
                article_to_save.search_vector = combined_text_for_fts # Atribui a string diretamente
                
                article_to_save.save(update_fields=['search_vector'])
                articles_processed_successfully += 1

                if articles_processed_successfully % 10 == 0 or articles_processed_successfully == total_articles:
                    print(f"  Progresso: {articles_processed_successfully}/{total_articles} artigos com vetor atualizado.")

            except Exception as e:
                print(f"  ERRO ao salvar ARTIGO ID {article_to_save.pk}, Título: '{article_to_save.title_truncado if hasattr(article_to_save, 'title_truncado') else article_to_save.title[:50]}'")
                print(f"    Erro específico: {e}")
                # print(f"    Título original (primeiros 100 chars): {str(article_to_save.title)[:100] if article_to_save.title else 'N/A'}")
                print("    O script será interrompido para análise do erro.")
                raise 
        
        if articles_batch:
            print(f"Fim do processamento do lote. Total atualizado com sucesso até agora: {articles_processed_successfully}")

    if articles_processed_successfully > 0:
        print(f"\nAtualização concluída! {articles_processed_successfully} artigos tiveram seus search_vectors atualizados.")
    elif total_articles > 0 :
        print("\nNenhum artigo teve seu search_vector atualizado. Verifique os logs de erro.")


# Linha para chamar a função quando o script for executado
if __name__ == '__main__':
    print("DEBUG: Script update_vectors.py está sendo executado diretamente.")
    try:
        print("DEBUG: Chamando update_existing_article_search_vectors()...")
        update_existing_article_search_vectors()
        print("DEBUG: update_existing_article_search_vectors() concluído (ou interrompido por erro).")
    except Exception as e:
        print(f"ERRO GERAL NO SCRIPT (fora da função principal ou após um 'raise'): {e}")
        import traceback
        traceback.print_exc()
    print("DEBUG: Fim da execução do script update_vectors.py.")