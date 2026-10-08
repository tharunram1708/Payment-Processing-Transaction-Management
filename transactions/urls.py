from django.urls import path

from transactions import views


urlpatterns = [
    path("transactions/", views.transaction_history, name="transaction-history"),
    path("transactions/<uuid:transaction_id>/", views.transaction_details, name="transaction-details"),
]
