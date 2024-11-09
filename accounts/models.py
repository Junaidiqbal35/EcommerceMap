from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.text import slugify


# Create your models here.
class UserManager(BaseUserManager):
    def create_user(self, email, username=None, password=None):
        if not email:
            raise ValueError("email is required")
        email = self.normalize_email(email)
        lower_letter_email = email.lower()
        print(lower_letter_email)
        user = self.model(
            email=lower_letter_email,
            username=username,
        )

        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, username, password):
        """creates new superuser with details """

        user = self.create_user(email, username, password)
        user.is_superuser = True
        user.is_staff = True
        user.save(using=self._db)
        return user


class User(AbstractUser):

    email = models.EmailField(max_length=100, unique=True)
    password = models.CharField(max_length=100, blank=False)
    username = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=200, db_index=True, blank=True, null=True)

    objects = UserManager()
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.username)
        super(User, self).save(*args, **kwargs)
