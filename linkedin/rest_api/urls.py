from django.urls import path

from linkedin.rest_api.views.campaigns import CampaignDetailView, CampaignListView
from linkedin.rest_api.views.jobs import JobDetailView, JobListView, LaneTriggerView
from linkedin.rest_api.views.profiles import ProfileDetailView, ProfileListView
from linkedin.rest_api.views.webhooks import WebhookDetailView, WebhookListCreateView

app_name = "rest_api"

urlpatterns = [
    # Profiles
    path("profiles/", ProfileListView.as_view(), name="profile-list"),
    path("profiles/<str:public_id>/", ProfileDetailView.as_view(), name="profile-detail"),
    # Campaigns
    path("campaigns/", CampaignListView.as_view(), name="campaign-list"),
    path("campaigns/<int:pk>/", CampaignDetailView.as_view(), name="campaign-detail"),
    # Lanes + Jobs
    path("lanes/<str:lane>/trigger/", LaneTriggerView.as_view(), name="lane-trigger"),
    path("jobs/", JobListView.as_view(), name="job-list"),
    path("jobs/<int:pk>/", JobDetailView.as_view(), name="job-detail"),
    # Webhooks
    path("webhooks/", WebhookListCreateView.as_view(), name="webhook-list"),
    path("webhooks/<int:pk>/", WebhookDetailView.as_view(), name="webhook-detail"),
]
