from django.contrib import admin
from .models import Client, Article, Source, FetchLog

@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("name", "source_type", "is_active", "url")
    list_filter = ("source_type", "is_active")
    search_fields = ("name", "url")

@admin.register(FetchLog)
class FetchLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "level", "client", "source", "message")
    list_filter = ("level", "created_at", "client", "source")
    search_fields = ("message",)
    readonly_fields = ("created_at",)


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("name",)
    filter_horizontal = ("users",)

@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "client", "published_at", "source")
    list_filter = ("client",)
    search_fields = ("title",)

