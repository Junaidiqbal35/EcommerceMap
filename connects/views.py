import json
# Create your views here.
import stripe
from django.conf import settings
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import ConnectPackage, ConnectTransaction
from .stripe_webhook_handlers import handle_successful_payment, handle_failed_payment

stripe.api_key = settings.STRIPE_SECRET_KEY


@login_required
def buy_connects(request):
    packages = ConnectPackage.objects.all()
    return render(request, 'payments/buy_connects.html', {'packages': packages})


@login_required
def my_connects(request):
    transactions = ConnectTransaction.objects.filter(user=request.user).order_by('-created_at')

    return render(request, "payments/my_connects.html", {
        "transactions": transactions,
        "connects": request.user.connects,
    })


@login_required
def create_checkout_session(request, package_id):
    try:
        package = get_object_or_404(ConnectPackage, stripe_plan_id=package_id)

        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            customer_email=request.user.email,
            line_items=[{
                'price': package.stripe_plan_id,
                'quantity': 1,
            }],
            mode='payment',

            success_url=request.build_absolute_uri(reverse('connects_page')),
            cancel_url=request.build_absolute_uri(reverse('payment_cancel')),
        )

        return redirect(session.url)

    except Exception as e:
        return render(request, 'payments/payment_error.html', {'error': str(e)})


@login_required
def payment_success(request):
    session_id = request.GET.get("session_id")

    if not session_id:
        return render(request, "payments/payment_error.html", {"error": "Invalid payment session."})

    try:
        session = stripe.checkout.Session.retrieve(session_id)

        if session.payment_status != "paid":
            messages.error(request, "invalid payment, or payment not completed")
            return render(request, "payments/payment_error.html", {"error": "Payment not completed."})

    except stripe.error.StripeError as e:
        messages.error(request, "invalid payment, or payment not completed")
        return render(request, "payments/payment_error.html", {"error": f"Stripe error: {str(e)}"})

    transactions = ConnectTransaction.objects.filter(user=request.user).order_by('-created_at')
    messages.success(request, "Your payment was successful")

    return render(request, 'payments/my_connects.html', {'transactions': transactions})


@csrf_exempt
@require_POST
def stripe_webhook(request):

    payload = request.body
    sig_header = request.headers.get('Stripe-Signature', '')

    webhook_secret = settings.STRIPE_WEBHOOK_SECRET_KEY
    event = None

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except ValueError:
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        return HttpResponse(status=400)

        # Handle different Stripe events
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']

        print(session)
        handle_successful_payment(session)

    elif event['type'] == 'checkout.session.payment_failed':
        session = event['data']['object']
        handle_failed_payment(session)

    return HttpResponse(status=200)


@login_required
def payment_cancel(request):
    return render(request, 'payments/payment_cancel.html')
