import os
from django.apps import AppConfig
from django.contrib.auth import get_user_model
from django.db.models.signals import post_migrate

def create_superuser(sender, **kwargs):
    User = get_user_model()
    username = os.getenv("DJANGO_SUPERUSER_USERNAME")
    email    = os.getenv("DJANGO_SUPERUSER_EMAIL")
    password = os.getenv("DJANGO_SUPERUSER_PASSWORD")

    if username and email and password:
        if not User.objects.filter(username=username).exists():
            User.objects.create_superuser(
                username=username,
                email=email,
                password=password
            )
            print(f"✨ Super‑usuário '{username}' criado automaticamente")

class CoreConfig(AppConfig):
    name = "core"

   
