from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

from .forms import RelationshipStatusAdminForm
from .models import Relationship, RelationshipStatus


class RelationshipInline(admin.TabularInline):
    model = Relationship
    raw_id_fields = ('from_user', 'to_user')
    extra = 1
    fk_name = 'from_user'


class UserRelationshipAdminMixin(object):
    inlines = (RelationshipInline,)


class RelationshipStatusAdmin(admin.ModelAdmin):
    form = RelationshipStatusAdminForm


class UserRelationshipAdmin(UserRelationshipAdminMixin, UserAdmin):
    pass

try:
    admin.site.unregister(get_user_model())
except admin.sites.NotRegistered:
    pass
admin.site.register(get_user_model(), UserRelationshipAdmin)

admin.site.register(RelationshipStatus, RelationshipStatusAdmin)
