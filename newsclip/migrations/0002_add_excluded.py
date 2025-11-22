from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('newsclip', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='article',
            name='excluded',
            field=models.BooleanField(
                default=False,
                verbose_name='Excluído manualmente',
                help_text='Artigos marcados assim não aparecem na lista'
            ),
        ),
    ]

