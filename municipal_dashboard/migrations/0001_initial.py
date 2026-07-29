# Generated manually for the isolated municipal_dashboard application.

import django.db.models.deletion
import django.core.validators
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Dimension",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Criado em")),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True, verbose_name="Atualizado em")),
                ("name", models.CharField(max_length=160, verbose_name="Nome")),
                (
                    "slug",
                    models.SlugField(
                        help_text="Identificador estável usado nas URLs e integrações.",
                        max_length=180,
                        unique=True,
                        verbose_name="Identificador",
                    ),
                ),
                ("description", models.TextField(blank=True, verbose_name="Descrição")),
                (
                    "accent_color",
                    models.CharField(
                        default="#1F5E8C",
                        max_length=7,
                        validators=[
                            django.core.validators.RegexValidator(
                                message="Informe uma cor hexadecimal no formato #RRGGBB.",
                                regex="^#[0-9A-Fa-f]{6}$",
                            )
                        ],
                        verbose_name="Cor de destaque",
                    ),
                ),
                (
                    "icon_name",
                    models.CharField(
                        blank=True,
                        help_text="Identificador do ícone usado pelo frontend, sem HTML.",
                        max_length=64,
                        validators=[
                            django.core.validators.RegexValidator(
                                message="Use apenas letras, números, hífen e sublinhado no nome do ícone.",
                                regex="^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$",
                            )
                        ],
                        verbose_name="Nome do ícone",
                    ),
                ),
                ("display_order", models.PositiveSmallIntegerField(db_index=True, default=0, verbose_name="Ordem")),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="Ativa")),
            ],
            options={
                "verbose_name": "Dimensão",
                "verbose_name_plural": "Dimensões",
                "ordering": ("display_order", "name", "pk"),
            },
        ),
        migrations.CreateModel(
            name="Axis",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Criado em")),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True, verbose_name="Atualizado em")),
                ("name", models.CharField(max_length=180, verbose_name="Nome")),
                (
                    "slug",
                    models.SlugField(
                        help_text="Identificador estável e único usado nas URLs e integrações.",
                        max_length=200,
                        unique=True,
                        verbose_name="Identificador",
                    ),
                ),
                ("description", models.TextField(blank=True, verbose_name="Descrição")),
                ("display_order", models.PositiveSmallIntegerField(db_index=True, default=0, verbose_name="Ordem")),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="Ativo")),
                (
                    "dimension",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="axes",
                        to="municipal_dashboard.dimension",
                        verbose_name="Dimensão",
                    ),
                ),
            ],
            options={
                "verbose_name": "Eixo",
                "verbose_name_plural": "Eixos",
                "ordering": ("dimension__display_order", "display_order", "name", "pk"),
                "indexes": [
                    models.Index(
                        fields=["dimension", "is_active", "display_order"],
                        name="mun_axis_navigation_idx",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="Indicator",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Criado em")),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True, verbose_name="Atualizado em")),
                ("name", models.CharField(max_length=240, verbose_name="Nome")),
                (
                    "slug",
                    models.SlugField(
                        help_text="Identificador estável usado nas APIs.",
                        max_length=260,
                        unique=True,
                        verbose_name="Identificador",
                    ),
                ),
                ("description", models.TextField(blank=True, verbose_name="Descrição")),
                ("methodology", models.TextField(blank=True, verbose_name="Metodologia")),
                ("unit", models.CharField(blank=True, max_length=40, verbose_name="Unidade")),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("mandatory", "Obrigatório"),
                            ("technical_proposal", "Proposta técnica"),
                            ("supplemental", "Contextual complementar"),
                        ],
                        db_index=True,
                        default="mandatory",
                        max_length=24,
                        verbose_name="Categoria",
                    ),
                ),
                (
                    "polarity",
                    models.CharField(
                        choices=[
                            ("higher", "Quanto maior, melhor"),
                            ("lower", "Quanto menor, melhor"),
                            ("neutral", "Neutro"),
                        ],
                        db_index=True,
                        default="neutral",
                        max_length=16,
                        verbose_name="Polaridade",
                    ),
                ),
                (
                    "frequency",
                    models.CharField(
                        choices=[
                            ("real_time", "Tempo real"),
                            ("daily", "Diária"),
                            ("weekly", "Semanal"),
                            ("monthly", "Mensal"),
                            ("quarterly", "Trimestral"),
                            ("semiannual", "Semestral"),
                            ("annual", "Anual"),
                            ("irregular", "Irregular"),
                        ],
                        db_index=True,
                        default="annual",
                        max_length=16,
                        verbose_name="Frequência",
                    ),
                ),
                (
                    "target_value",
                    models.DecimalField(
                        blank=True,
                        decimal_places=6,
                        help_text="Meta opcional; uma medição pode sobrescrevê-la para um período específico.",
                        max_digits=22,
                        null=True,
                        verbose_name="Meta padrão",
                    ),
                ),
                ("target_deadline", models.DateField(blank=True, null=True, verbose_name="Prazo da meta")),
                ("source_name", models.CharField(blank=True, max_length=240, verbose_name="Fonte padrão")),
                ("source_url", models.URLField(blank=True, max_length=1000, verbose_name="URL da fonte")),
                ("display_order", models.PositiveSmallIntegerField(db_index=True, default=0, verbose_name="Ordem")),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="Ativo")),
                (
                    "axis",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="indicators",
                        to="municipal_dashboard.axis",
                        verbose_name="Eixo",
                    ),
                ),
            ],
            options={
                "verbose_name": "Indicador",
                "verbose_name_plural": "Indicadores",
                "ordering": (
                    "axis__dimension__display_order",
                    "axis__display_order",
                    "display_order",
                    "name",
                    "pk",
                ),
                "indexes": [
                    models.Index(fields=["axis", "is_active", "display_order"], name="mun_indicator_nav_idx"),
                    models.Index(fields=["frequency", "is_active"], name="mun_indicator_freq_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="Measurement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Criado em")),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True, verbose_name="Atualizado em")),
                ("period_start", models.DateField(db_index=True, verbose_name="Início do período")),
                ("period_end", models.DateField(db_index=True, verbose_name="Fim do período")),
                ("value", models.DecimalField(decimal_places=6, max_digits=22, verbose_name="Valor")),
                (
                    "target_value",
                    models.DecimalField(
                        blank=True,
                        decimal_places=6,
                        max_digits=22,
                        null=True,
                        verbose_name="Meta do período",
                    ),
                ),
                (
                    "quality",
                    models.CharField(
                        choices=[
                            ("official", "Oficial"),
                            ("verified", "Verificada"),
                            ("provisional", "Provisória"),
                            ("estimated", "Estimada"),
                            ("revised", "Revisada"),
                        ],
                        db_index=True,
                        default="provisional",
                        max_length=16,
                        verbose_name="Qualidade",
                    ),
                ),
                (
                    "source_name",
                    models.CharField(
                        blank=True,
                        help_text="Quando vazio, a API usa a fonte padrão do indicador.",
                        max_length=240,
                        verbose_name="Fonte",
                    ),
                ),
                ("source_url", models.URLField(blank=True, max_length=1000, verbose_name="URL da fonte")),
                (
                    "observed_at",
                    models.DateTimeField(
                        db_index=True,
                        default=django.utils.timezone.now,
                        verbose_name="Observado/recebido em",
                    ),
                ),
                (
                    "breakdown",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="Objeto JSON para recortes por região, sexo, faixa etária ou outra categoria.",
                        verbose_name="Detalhamento",
                    ),
                ),
                ("note", models.TextField(blank=True, verbose_name="Observação")),
                (
                    "indicator",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="measurements",
                        to="municipal_dashboard.indicator",
                        verbose_name="Indicador",
                    ),
                ),
            ],
            options={
                "verbose_name": "Medição",
                "verbose_name_plural": "Medições",
                "ordering": ("indicator_id", "-period_end", "-period_start", "-updated_at", "-pk"),
                "indexes": [
                    models.Index(fields=["indicator", "-period_end"], name="mun_meas_latest_idx"),
                    models.Index(fields=["-updated_at"], name="mun_meas_updated_idx"),
                    models.Index(fields=["quality", "-period_end"], name="mun_meas_quality_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("indicator", "period_start", "period_end"),
                        name="mun_meas_period_uniq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("period_end__gte", models.F("period_start"))),
                        name="mun_meas_period_order",
                    ),
                ],
            },
        ),
    ]
