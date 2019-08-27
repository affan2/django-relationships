from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model


def require_user(view):
    def inner(request, username, *args, **kwargs):
        user = get_object_or_404(get_user_model(), username=username)
        return view(request, user, *args, **kwargs)
    return inner
