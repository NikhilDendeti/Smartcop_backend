from django.urls import path

from users.authn import views

urlpatterns = [
    path("otp/request/", views.otp_request),
    path("otp/verify/", views.otp_verify),
    path("register/request/", views.register_request),
    path("register/verify/", views.register_verify),
    path("token/refresh/", views.token_refresh),
    path("logout/", views.logout),
    path("me/", views.me),
]
