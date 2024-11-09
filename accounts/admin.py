from allauth.account.models import EmailAddress
from django.contrib import admin
from django.contrib.auth.models import Group

from accounts.models import User
admin.site.unregister(Group)
admin.site.unregister(EmailAddress)
# Register your models here.
admin.site.register(User)