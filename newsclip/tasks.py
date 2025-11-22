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
        return f"Success: News fetched for client {client_id}"
        
    except Exception as e:
        logger.error(f"Error in fetch_news_task for client_id={client_id}: {e}")
        return f"Error: {e}"
