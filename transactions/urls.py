from django.urls import path

from transactions import views


urlpatterns = [
    path("auth/register/", views.register, name="auth-register"),
    path("auth/login/", views.login, name="auth-login"),
    path("auth/logout/", views.logout, name="auth-logout"),
    path("auth/me/", views.current_user, name="auth-me"),
    path("cards/", views.saved_cards, name="saved-cards"),
    path("cards/<int:card_id>/", views.delete_saved_card, name="delete-saved-card"),
    path("transactions/", views.transaction_history, name="transaction-history"),
    path("transactions/<uuid:transaction_id>/", views.transaction_details, name="transaction-details"),
]
