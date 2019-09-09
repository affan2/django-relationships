from django.db import models
# from django.contrib.auth.models import User
from django.contrib.auth import get_user_model


class SomeModel(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='user', on_delete=models.CASCADE)
