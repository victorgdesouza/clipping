from django.core.management import call_command
from django.utils import timezone
import logging

from newsclip.models import NewsFetchJob

logger = logging.getLogger('newsclip')

def fetch_news_task(client_id, job_id=None):
    """
    Task to be executed by Django Q to fetch news for a client.
    """
    start_time = timezone.now()
    logger.info(f"Starting fetch_news_task for client_id={client_id} at {start_time}")
    
    job = None
    if job_id:
        job = NewsFetchJob.objects.filter(pk=job_id).first()
        if job:
            job.status = "running"
            job.started_at = start_time
            job.error_message = ""
            job.save(update_fields=["status", "started_at", "error_message", "updated_at"])

    try:
        # Call the existing management command
        # This reuses the logic already implemented in the command
        call_command("fetch_news", "--client-id", str(client_id))
        
        logger.info(f"Successfully completed fetch_news_task for client_id={client_id}")
        if job:
            job.status = "completed"
            job.finished_at = timezone.now()
            job.result_message = f"Busca concluida para o cliente {client_id}."
            job.save(update_fields=["status", "finished_at", "result_message", "updated_at"])
        return f"Busca concluida para o cliente {client_id}."
        
    except Exception as e:
        logger.exception(f"Error in fetch_news_task for client_id={client_id}: {e}")
        if job:
            job.status = "failed"
            job.finished_at = timezone.now()
            job.error_message = str(e)
            job.save(update_fields=["status", "finished_at", "error_message", "updated_at"])
        raise
