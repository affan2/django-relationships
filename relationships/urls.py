from django.urls import re_path

from .views import get_follower_subset, get_following_subset, \
    get_following, get_followers, relationship_handler, relationship_list, relationship_redirect

urlpatterns = [
    'relationships.views',
    re_path(r'^$', relationship_redirect, name='relationship_list_base'),
    re_path(r'^(?P<username>[\w.@+-]+)/(?:(?P<status_slug>[\w-]+)/)?$', relationship_list, name='relationship_list'),
    re_path(r'^add/(?P<username>[\w.@+-]+)/(?P<status_slug>[\w-]+)/$', relationship_handler, {'add': True},
            name='relationship_add'),
    re_path(r'^remove/(?P<username>[\w.@+-]+)/(?P<status_slug>[\w-]+)/$', relationship_handler, {'add': False},
            name='relationship_remove'),
    re_path(r'^followers/(?P<content_type_id>\d+)/(?P<object_id>\d+)/$', get_followers, name='get_followers'),
    re_path(r'^following/(?P<content_type_id>\d+)/(?P<object_id>\d+)/$', get_following, name='get_following'),
    re_path(r'^following_subset/(?P<content_type_id>\d+)/(?P<object_id>\d+)/(?P<sIndex>\d+)/(?P<lIndex>\d+)/$',
            get_following_subset, name='get_following_subset'),
    re_path(r'^follower_subset/(?P<content_type_id>\d+)/(?P<object_id>\d+)/(?P<sIndex>\d+)/(?P<lIndex>\d+)/$',
            get_follower_subset, name='get_follower_subset'),
]
