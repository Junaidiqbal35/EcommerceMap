import stripe
from django.core.mail import send_mail

from accounts.models import User
from connects.models import ConnectTransaction, ConnectPackage


def handle_successful_payment(session):
    email = session.get("customer_email")

    try:
        user = User.objects.get(email=email)
        line_items = stripe.checkout.Session.list_line_items(session["id"])
        print(f'{line_items}')
        package_id = line_items["data"][0]["price"]["id"] if line_items["data"] else None
        print(package_id)

        package = ConnectPackage.objects.filter(stripe_plan_id =package_id).first()

        if not package:
            print(f"❌ Package not found: {package}")
            return

        user.connects += package.connects
        user.save()

        ConnectTransaction.objects.create(
            user=user,
            package=package,
            amount_paid=package.price,
            connects_added=package.connects,
            is_completed=True
        )

        print(f"✅ Payment successful! {package.connects} connects added to {user.email}")

    except User.DoesNotExist:
        print("❌ User not found for payment session.")
    except Exception as e:
        print(f"⚠️ Error processing payment: {e}")


def handle_failed_payment(session):
    email = session.get("customer_email")

    try:
        user = User.objects.get(email=email)
        package_name = session['display_items'][0]['custom']['name']

        send_mail(
            subject="Payment Failed - Connects Not Added",
            message="Your recent payment attempt for purchasing connects was unsuccessful. "
                    "Please try again or update your payment method.",
            from_email="support@yourwebsite.com",
            recipient_list=[user.email],
        )

        print(f"⚠️ Payment failed for {user.email} - No connects added.")

    except User.DoesNotExist:
        print("❌ User not found for failed payment session.")
    except Exception as e:
        print(f"⚠️ Error handling failed payment: {e}")