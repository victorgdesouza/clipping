# Generated by Django 5.2 on 2025-04-28 00:54

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Client',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, verbose_name='Nome do cliente')),
                ('keywords', models.TextField(help_text='Separe por vírgulas')),
                ('domains', models.TextField(blank=True, help_text='Ex: g1.globo.com, uol.com.br', verbose_name='Domínios confiáveis (vírgula-separados)')),
                ('users', models.ManyToManyField(help_text='Quem pode ver/editar este cliente', related_name='clients', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='Article',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=300, verbose_name='Título')),
                ('url', models.URLField(unique=True, verbose_name='Link')),
                ('published_at', models.DateTimeField(blank=True, null=True, verbose_name='Publicação')),
                ('source', models.CharField(blank=True, max_length=200, verbose_name='Fonte')),
                ('summary', models.TextField(blank=True, verbose_name='Resumo')),
                ('topic', models.CharField(blank=True, max_length=100, verbose_name='Tópico')),
                ('excluded', models.BooleanField(default=False, help_text='Artigos marcados assim não aparecem na lista', verbose_name='Excluído manualmente')),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='articles', to='newsclip.client')),
            ],
        ),
    ]
