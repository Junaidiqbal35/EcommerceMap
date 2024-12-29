from django.contrib.auth.forms import UserCreationForm

from accounts.models import User


class CreateUserForm(UserCreationForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'username', 'email']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['first_name'].required = True
        self.fields['last_name'].required = True
        self.fields['first_name'].widget.attrs.update({'class': 'input_pox'})
        self.fields['last_name'].widget.attrs.update({'class': 'input_pox'})
