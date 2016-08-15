from django.conf import settings
from django.conf.urls import include, url

from arcutils import admin
from arcutils.drf.routers import DefaultRouter
import arcutils.cas.urls

from . import views
from .locations.views import LocationViewSet


urlpatterns = [
    # Home
    url(r'^$', views.AppView.as_view(app_key=settings.HOME_PAGE_APP_KEY), name='home'),
    url(r'^admin$', views.AppView.as_view(app_key='admin'), name='admin'),

    # Admin
    url(r'^django-admin/', admin.cas_site.urls),

    # Auth
    url(r'', include(arcutils.cas.urls)),
]

router = DefaultRouter()
urlpatterns += router.urls
