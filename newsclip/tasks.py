from django.core.management import call_command
from django.utils import timezone
import logging

logger = logging.getLogger('newsclip')

def fetch_news_task(client_id):
    """
    Task to be executed by Django Q to fetch news for a client.
    """
    start_time = timezone.now()
    logger.info(f"Starting fetch_news_task for client_id={client_id} at {start_time}")
    
    try:
        # Call the existing management command
        # This reuses the logic already implemented in the command
        call_command("fetch_news", "--client-id", str(client_id))
        
        logger.info(f"Successfully completed fetch_news_task for client_id={client_id}")
        return f"Busca concluida para o cliente {client_id}."
        
    except Exception as e:
        logger.exception(f"Error in fetch_news_task for client_id={client_id}: {e}")
        raise
