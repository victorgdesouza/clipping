from django.apps import apps
from django.db.models.signals import post_migrate
from django.dispatch import receiver

@receiver(post_migrate)
def create_google_socialapp(sender, **kwargs):
    if sender.name != 'newsclip':
        return
    SocialApp = apps.get_model('socialaccount', 'SocialApp')
    # aqui você cria ou atualiza o SocialApp do Google
    SocialApp.objects.get_or_create(
        provider='google',
        defaults={ 'client_id': '…', 'secret': '…', 'name': 'Google' }
    )
