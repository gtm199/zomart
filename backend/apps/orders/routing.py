from django.urls import re_path

from .consumers import TrackConsumer

websocket_urlpatterns = [
    re_path(r"^ws/track/(?P<order_id>\d+)/$", TrackConsumer.as_asgi()),
]