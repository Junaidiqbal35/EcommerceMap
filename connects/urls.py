from django.urls import path
from . import views

urlpatterns = [
    path('buy-connects/', views.buy_connects, name='buy_connects'),
    path('create-checkout-session/<str:package_id>/', views.create_checkout_session, name='create_checkout_session'),
    path('payments/success/', views.payment_success, name='payment_success'),
    path('payments/cancel/', views.payment_cancel, name='payment_cancel'),
    path('stripe-webhook/', views.stripe_webhook, name='stripe_webhook'),
    path('my-connects/', views.my_connects, name='connects_page'),

]
