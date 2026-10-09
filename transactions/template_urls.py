from django.urls import path

from transactions import views


urlpatterns = [
    path("", views.home_page, name="home-page"),
    path("register/", views.register_page, name="register-page"),
    path("login/", views.login_page, name="login-page"),
    path("logout/", views.logout_page, name="logout-page"),
    path("cards/", views.card_list_page, name="card-list-page"),
    path("cards/<int:card_id>/delete/", views.delete_card_page, name="delete-card-page"),
]
