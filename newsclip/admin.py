from django.contrib import admin
from .models import (
    Article,
    Client,
    DiscoveryResult,
    DiscoveryRun,
    FetchLog,
    NewsFetchJob,
    RelevanceAuditLog,
    Source,
    SourceEndpoint,
)


class SourceEndpointInline(admin.TabularInline):
    model = SourceEndpoint
    extra = 0

@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("name", "domain", "source_type", "status", "confidence_score", "is_active")
    list_filter = ("source_type", "status", "is_active", "discovered_automatically")
    search_fields = ("name", "domain", "url")
    readonly_fields = ("first_discovered_at", "last_discovered_at", "discovery_count")
    inlines = (SourceEndpointInline,)


@admin.register(DiscoveryResult)
class DiscoveryResultAdmin(admin.ModelAdmin):
    list_display = ("discovered_at", "client", "provider", "is_relevant", "relevance_score", "title")
    list_filter = ("provider", "is_relevant", "discovered_at")
    search_fields = ("title", "description", "url", "query")
    readonly_fields = ("discovered_at",)


@admin.register(DiscoveryRun)
class DiscoveryRunAdmin(admin.ModelAdmin):
    list_display = ("started_at", "client", "provider", "status", "queries_count", "results_count", "new_sources_count")
    list_filter = ("provider", "status", "started_at")
    readonly_fields = ("started_at", "finished_at")

@admin.register(FetchLog)
class FetchLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "level", "client", "source", "message")
    list_filter = ("level", "created_at", "client", "source")
    search_fields = ("message",)
    readonly_fields = ("created_at",)


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name", "name_variations", "context_terms", "keywords")
    filter_horizontal = ("users",)

@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "client", "published_at", "source", "validation_status", "relevance_score")
    list_filter = ("client", "validation_status", "provider")
    search_fields = ("title",)


@admin.register(RelevanceAuditLog)
class RelevanceAuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "client", "decision", "relevance_score", "provider", "title")
    list_filter = ("decision", "provider", "created_at", "client")
    search_fields = ("title", "url", "query", "relevance_reason")
    readonly_fields = ("created_at",)


@admin.register(NewsFetchJob)
class NewsFetchJobAdmin(admin.ModelAdmin):
    list_display = ("created_at", "client", "status", "started_at", "finished_at", "task_id")
    list_filter = ("status", "created_at", "client")
    search_fields = ("task_id", "error_message", "result_message")
    readonly_fields = ("created_at", "updated_at")

