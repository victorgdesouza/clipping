from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True, db_index=True)

    class Meta:
        abstract = True


class Dimension(TimeStampedModel):
    name = models.CharField("Nome", max_length=160)
    slug = models.SlugField(
        "Identificador",
        max_length=180,
        unique=True,
        help_text="Identificador estável usado nas URLs e integrações.",
    )
    description = models.TextField("Descrição", blank=True)
    accent_color = models.CharField(
        "Cor de destaque",
        max_length=7,
        default="#1F5E8C",
        validators=[
            RegexValidator(
                regex=r"^#[0-9A-Fa-f]{6}$",
                message="Informe uma cor hexadecimal no formato #RRGGBB.",
            )
        ],
    )
    icon_name = models.CharField(
        "Nome do ícone",
        max_length=64,
        blank=True,
        help_text="Identificador do ícone usado pelo frontend, sem HTML.",
        validators=[
            RegexValidator(
                regex=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$",
                message="Use apenas letras, números, hífen e sublinhado no nome do ícone.",
            )
        ],
    )
    display_order = models.PositiveSmallIntegerField("Ordem", default=0, db_index=True)
    is_active = models.BooleanField("Ativa", default=True, db_index=True)

    class Meta:
        ordering = ("display_order", "name", "pk")
        verbose_name = "Dimensão"
        verbose_name_plural = "Dimensões"

    def __str__(self):
        return self.name


class Axis(TimeStampedModel):
    dimension = models.ForeignKey(
        Dimension,
        on_delete=models.CASCADE,
        related_name="axes",
        verbose_name="Dimensão",
    )
    name = models.CharField("Nome", max_length=180)
    slug = models.SlugField(
        "Identificador",
        max_length=200,
        unique=True,
        help_text="Identificador estável e único usado nas URLs e integrações.",
    )
    description = models.TextField("Descrição", blank=True)
    display_order = models.PositiveSmallIntegerField("Ordem", default=0, db_index=True)
    is_active = models.BooleanField("Ativo", default=True, db_index=True)

    class Meta:
        ordering = ("dimension__display_order", "display_order", "name", "pk")
        verbose_name = "Eixo"
        verbose_name_plural = "Eixos"
        indexes = [
            models.Index(fields=("dimension", "is_active", "display_order"), name="mun_axis_navigation_idx"),
        ]

    def __str__(self):
        return f"{self.dimension.name} — {self.name}"


class Indicator(TimeStampedModel):
    class Kind(models.TextChoices):
        MANDATORY = "mandatory", "Obrigatório"
        TECHNICAL_PROPOSAL = "technical_proposal", "Proposta técnica"
        SUPPLEMENTAL = "supplemental", "Contextual complementar"

    class Polarity(models.TextChoices):
        HIGHER_IS_BETTER = "higher", "Quanto maior, melhor"
        LOWER_IS_BETTER = "lower", "Quanto menor, melhor"
        NEUTRAL = "neutral", "Neutro"

    class Frequency(models.TextChoices):
        REAL_TIME = "real_time", "Tempo real"
        DAILY = "daily", "Diária"
        WEEKLY = "weekly", "Semanal"
        MONTHLY = "monthly", "Mensal"
        QUARTERLY = "quarterly", "Trimestral"
        SEMIANNUAL = "semiannual", "Semestral"
        ANNUAL = "annual", "Anual"
        IRREGULAR = "irregular", "Irregular"

    axis = models.ForeignKey(
        Axis,
        on_delete=models.CASCADE,
        related_name="indicators",
        verbose_name="Eixo",
    )
    name = models.CharField("Nome", max_length=240)
    slug = models.SlugField(
        "Identificador",
        max_length=260,
        unique=True,
        help_text="Identificador estável usado nas APIs.",
    )
    description = models.TextField("Descrição", blank=True)
    methodology = models.TextField("Metodologia", blank=True)
    unit = models.CharField("Unidade", max_length=40, blank=True)
    kind = models.CharField(
        "Categoria",
        max_length=24,
        choices=Kind.choices,
        default=Kind.MANDATORY,
        db_index=True,
    )
    polarity = models.CharField(
        "Polaridade",
        max_length=16,
        choices=Polarity.choices,
        default=Polarity.NEUTRAL,
        db_index=True,
    )
    frequency = models.CharField(
        "Frequência",
        max_length=16,
        choices=Frequency.choices,
        default=Frequency.ANNUAL,
        db_index=True,
    )
    target_value = models.DecimalField(
        "Meta padrão",
        max_digits=22,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Meta opcional; uma medição pode sobrescrevê-la para um período específico.",
    )
    target_deadline = models.DateField("Prazo da meta", null=True, blank=True)
    source_name = models.CharField("Fonte padrão", max_length=240, blank=True)
    source_url = models.URLField("URL da fonte", max_length=1000, blank=True)
    display_order = models.PositiveSmallIntegerField("Ordem", default=0, db_index=True)
    is_active = models.BooleanField("Ativo", default=True, db_index=True)

    class Meta:
        ordering = (
            "axis__dimension__display_order",
            "axis__display_order",
            "display_order",
            "name",
            "pk",
        )
        verbose_name = "Indicador"
        verbose_name_plural = "Indicadores"
        indexes = [
            models.Index(fields=("axis", "is_active", "display_order"), name="mun_indicator_nav_idx"),
            models.Index(fields=("frequency", "is_active"), name="mun_indicator_freq_idx"),
        ]

    def __str__(self):
        return f"{self.axis.name} — {self.name}"


class Measurement(TimeStampedModel):
    class Quality(models.TextChoices):
        OFFICIAL = "official", "Oficial"
        VERIFIED = "verified", "Verificada"
        PROVISIONAL = "provisional", "Provisória"
        ESTIMATED = "estimated", "Estimada"
        REVISED = "revised", "Revisada"

    indicator = models.ForeignKey(
        Indicator,
        on_delete=models.CASCADE,
        related_name="measurements",
        verbose_name="Indicador",
    )
    period_start = models.DateField("Início do período", db_index=True)
    period_end = models.DateField("Fim do período", db_index=True)
    value = models.DecimalField("Valor", max_digits=22, decimal_places=6)
    target_value = models.DecimalField(
        "Meta do período",
        max_digits=22,
        decimal_places=6,
        null=True,
        blank=True,
    )
    quality = models.CharField(
        "Qualidade",
        max_length=16,
        choices=Quality.choices,
        default=Quality.PROVISIONAL,
        db_index=True,
    )
    source_name = models.CharField(
        "Fonte",
        max_length=240,
        blank=True,
        help_text="Quando vazio, a API usa a fonte padrão do indicador.",
    )
    source_url = models.URLField("URL da fonte", max_length=1000, blank=True)
    observed_at = models.DateTimeField(
        "Observado/recebido em",
        default=timezone.now,
        db_index=True,
    )
    breakdown = models.JSONField(
        "Detalhamento",
        default=dict,
        blank=True,
        help_text="Objeto JSON para recortes por região, sexo, faixa etária ou outra categoria.",
    )
    note = models.TextField("Observação", blank=True)

    class Meta:
        ordering = ("indicator_id", "-period_end", "-period_start", "-updated_at", "-pk")
        verbose_name = "Medição"
        verbose_name_plural = "Medições"
        constraints = [
            models.UniqueConstraint(
                fields=("indicator", "period_start", "period_end"),
                name="mun_meas_period_uniq",
            ),
            models.CheckConstraint(
                condition=Q(period_end__gte=F("period_start")),
                name="mun_meas_period_order",
            ),
        ]
        indexes = [
            models.Index(fields=("indicator", "-period_end"), name="mun_meas_latest_idx"),
            models.Index(fields=("-updated_at",), name="mun_meas_updated_idx"),
            models.Index(fields=("quality", "-period_end"), name="mun_meas_quality_idx"),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.period_start and self.period_end and self.period_end < self.period_start:
            errors["period_end"] = "O fim do período não pode ser anterior ao início."
        if not isinstance(self.breakdown, dict):
            errors["breakdown"] = "O detalhamento deve ser um objeto JSON."
        if errors:
            raise ValidationError(errors)

    @property
    def effective_target_value(self):
        if self.target_value is not None:
            return self.target_value
        return self.indicator.target_value

    @property
    def effective_source_name(self):
        return self.source_name or self.indicator.source_name

    @property
    def effective_source_url(self):
        return self.source_url or self.indicator.source_url

    def __str__(self):
        return f"{self.indicator.name}: {self.period_start:%d/%m/%Y}–{self.period_end:%d/%m/%Y}"
