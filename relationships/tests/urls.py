from django.urls import re_path, include
from django.contrib import admin
admin.autodiscover()

urlpatterns = ['',
    (r'^admin/', include(admin.site.urls)),
    re_path(r'^relationships/', include('relationships.urls')),
]
