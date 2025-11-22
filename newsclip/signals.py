from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Article

@receiver(post_save, sender=Article)
def update_search_vector(sender, instance, created, **kwargs):
    """
    Atualiza o campo search_vector sempre que um artigo é salvo.
    """
    # Evita recursão infinita se o save for apenas para o search_vector
    if kwargs.get('update_fields') and 'search_vector' in kwargs['update_fields']:
        return

    title_val = instance.title if instance.title is not None else ''
    summary_val = instance.summary if instance.summary is not None else ''
    content_val = instance.content if instance.content is not None else ''

    # Para SQLite, concatenamos os campos
    combined_text_for_fts = f"{title_val} {summary_val} {content_val}"
    
    # Atualiza apenas o campo search_vector
    instance.search_vector = combined_text_for_fts
    instance.save(update_fields=['search_vector'])
