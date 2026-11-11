"""Live delivery tracking without any map service: the rider's position is pushed to the customer, and the time left is
a straight-line estimate. Turn-by-turn navigation is done by the rider's own Google Maps app, opened from a link."""
import json
import math

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.utils import timezone

from apps.orders.models import DeliveryTrack, Order

EARTH_KM = 6371.0088
ROAD_FACTOR = 1.3         # roads are longer than the straight line between two points
AVERAGE_KMH = 20          # a rough speed for a bike in town


def haversine_km(lat1, lng1, lat2, lng2):
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp, dl = p2 - p1, math.radians(float(lng2) - float(lng1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(a))


def valid_point(lat, lng):
    try:
        return -90 <= float(lat) <= 90 and -180 <= float(lng) <= 180 and not (float(lat) == 0 and float(lng) == 0)
    except (TypeError, ValueError):
        return False


def eta_for(track, order):
    """(distance_km, eta_minutes): the straight line to the customer, stretched a little to allow for the roads."""
    dest = order.position()
    if dest is None or track is None or track.rider_lat is None:
        return None, None
    km = haversine_km(track.rider_lat, track.rider_lng, *dest) * ROAD_FACTOR
    return round(km, 1), max(1, math.ceil(km / AVERAGE_KMH * 60) + 1)


# ---------------- the rider's updates, pushed to the customer ----------------
def publish(order_id, data):
    """Send a message to every customer screen watching this order. Never raises."""
    try:
        layer = get_channel_layer()
        if layer is not None:
            async_to_sync(layer.group_send)(f"track_{order_id}", {"type": "track.message", "data": json.loads(json.dumps(data, default=str))})
    except Exception:
        pass


def notify_refresh(order):
    """Tell watching screens that something changed (status, arrival, a moved pin...), so they load the order again."""
    transaction.on_commit(lambda: publish(order.pk, {"type": "refresh"}))


def update_position(track, *, lat, lng, heading=None, speed=None, accuracy=None):
    track.rider_lat, track.rider_lng = lat, lng
    track.heading, track.speed, track.accuracy = heading, speed, accuracy
    track.updated_at = timezone.now()
    track.save(update_fields=["rider_lat", "rider_lng", "heading", "speed", "accuracy", "updated_at"])
    distance_km, eta_minutes = eta_for(track, track.order)
    publish(track.order_id, {
        "type": "position", "lat": lat, "lng": lng, "heading": heading, "updated_at": track.updated_at,
        "arrived": track.arrived_at is not None, "eta_minutes": eta_minutes, "distance_km": distance_km})


def clear(order):
    """Delivered or cancelled: forget where the rider was."""
    DeliveryTrack.objects.filter(order=order).update(rider_lat=None, rider_lng=None, heading=None, speed=None, accuracy=None)


# ---------------- what the customer sees when the screen opens ----------------
def track_payload(order):
    shop = order.shop
    dest = order.position()
    track = getattr(order, "track", None)
    live = bool(track and track.rider_lat is not None and order.status == Order.Status.OUT_FOR_DELIVERY)
    shop_point = (float(shop.latitude), float(shop.longitude)) if shop.latitude is not None and shop.longitude is not None else None

    distance_km = eta_minutes = None
    if live:
        distance_km, eta_minutes = eta_for(track, order)
    elif shop_point and dest:
        distance_km = round(haversine_km(*shop_point, *dest) * ROAD_FACTOR, 1)

    rider = None
    if order.rider and order.status == Order.Status.OUT_FOR_DELIVERY:
        rider = {"name": order.rider.first_name or order.rider.username, "phone": order.rider.phone,
                 "lat": track.rider_lat if live else None, "lng": track.rider_lng if live else None,
                 "heading": track.heading if live else None, "updated_at": track.updated_at if live else None,
                 "arrived": bool(track and track.arrived_at)}
    return {
        "status": order.status, "fulfilment": order.fulfilment,
        "pin": order.delivery_pin if order.fulfilment == Order.Fulfilment.DELIVERY and order.status == Order.Status.OUT_FOR_DELIVERY else None,
        "shop": {"name": shop.name, "phone": shop.phone, "lat": shop_point[0] if shop_point else None, "lng": shop_point[1] if shop_point else None},
        "destination": {"lat": dest[0], "lng": dest[1], "address": order.delivery_address} if dest else None,
        "rider": rider, "distance_km": distance_km, "eta_minutes": eta_minutes,
    }