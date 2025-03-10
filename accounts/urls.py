from django.urls import path
from . import views

urlpatterns = [
    path('signup/', views.SignUpView.as_view(), name='account_signup'),
    path("logout/", views.logout_view, name='logout'),

]