# linkedin/admin.py
from django.contrib import admin

from linkedin.models import ActionJob, ApiKey, Campaign, LinkedInProfile, SearchKeyword, WebhookSubscription


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ("department", "booking_link", "is_partner", "action_fraction")
    raw_id_fields = ("department",)


@admin.register(LinkedInProfile)
class LinkedInProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "linkedin_username", "active")
    list_filter = ("active",)
    raw_id_fields = ("user",)


@admin.register(SearchKeyword)
class SearchKeywordAdmin(admin.ModelAdmin):
    list_display = ("keyword", "campaign", "used", "used_at")
    list_filter = ("used", "campaign")
    raw_id_fields = ("campaign",)


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ["name", "active", "created_at"]
    list_filter = ["active"]
    readonly_fields = ["key_hash", "created_at"]


@admin.register(ActionJob)
class ActionJobAdmin(admin.ModelAdmin):
    list_display = ["id", "lane", "status", "campaign", "created_at", "updated_at"]
    list_filter = ["status", "lane", "campaign"]
    readonly_fields = ["created_at", "updated_at", "result"]
    search_fields = ["lane", "status"]


@admin.register(WebhookSubscription)
class WebhookSubscriptionAdmin(admin.ModelAdmin):
    list_display = ["id", "url", "active", "campaign", "created_at"]
    list_filter = ["active", "campaign"]
    readonly_fields = ["created_at"]
