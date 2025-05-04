from django.contrib import admin
from .models import Client, Article

@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("name",)
    filter_horizontal = ("users",)

@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "client", "published_at", "source")
    list_filter = ("client",)
    search_fields = ("title",)

