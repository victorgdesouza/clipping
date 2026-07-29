from django.contrib import admin

from .models import Axis, Dimension, Indicator, Measurement


class AxisInline(admin.TabularInline):
    model = Axis
    fields = ("name", "slug", "display_order", "is_active")
    extra = 0
    show_change_link = True


@admin.register(Dimension)
class DimensionAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "slug",
        "accent_color",
        "icon_name",
        "display_order",
        "is_active",
        "updated_at",
    )
    list_editable = ("display_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "slug", "description")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("created_at", "updated_at")
    inlines = (AxisInline,)


class IndicatorInline(admin.TabularInline):
    model = Indicator
    fields = ("name", "slug", "unit", "frequency", "display_order", "is_active")
    extra = 0
    show_change_link = True


@admin.register(Axis)
class AxisAdmin(admin.ModelAdmin):
    list_display = ("name", "dimension", "slug", "display_order", "is_active", "updated_at")
    list_editable = ("display_order", "is_active")
    list_filter = ("dimension", "is_active")
    search_fields = ("name", "slug", "description", "dimension__name")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("dimension",)
    readonly_fields = ("created_at", "updated_at")
    inlines = (IndicatorInline,)
    list_select_related = ("dimension",)


@admin.register(Indicator)
class IndicatorAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "axis",
        "unit",
        "kind",
        "polarity",
        "frequency",
        "target_value",
        "display_order",
        "is_active",
        "updated_at",
    )
    list_editable = ("display_order", "is_active")
    list_filter = (
        "is_active",
        "kind",
        "polarity",
        "frequency",
        "axis__dimension",
        "axis",
    )
    search_fields = (
        "name",
        "slug",
        "description",
        "methodology",
        "source_name",
        "axis__name",
        "axis__dimension__name",
    )
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("axis",)
    readonly_fields = ("created_at", "updated_at")
    list_select_related = ("axis", "axis__dimension")


@admin.register(Measurement)
class MeasurementAdmin(admin.ModelAdmin):
    list_display = (
        "indicator",
        "period_start",
        "period_end",
        "value",
        "target_value",
        "quality",
        "source_name",
        "observed_at",
        "updated_at",
    )
    list_filter = (
        "quality",
        "indicator__axis__dimension",
        "indicator__axis",
        "period_end",
    )
    search_fields = (
        "indicator__name",
        "indicator__slug",
        "source_name",
        "note",
    )
    autocomplete_fields = ("indicator",)
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "period_end"
    list_select_related = ("indicator", "indicator__axis", "indicator__axis__dimension")
