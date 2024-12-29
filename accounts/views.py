from allauth.account.views import SignupView
from django.contrib import messages
from django.shortcuts import render, redirect

from accounts.forms import CreateUserForm


# Create your views here.
class SignUpView(SignupView):
    template_name = 'account/registration.html'
    form_class = CreateUserForm

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, {'form': self.form_class})

    def post(self, request, *args, **kwargs):
        form = self.form_class(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Your Account Is Created! Get Login.')
            return redirect('account_login')
        return render(request, self.template_name, {'form': form})
