from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.shops.models import ShopMembership
from apps.shops.roles import Cap
from core.tenancy import ShopAccess, ShopScopedMixin
from services import order_service, tracking_service
from services.exceptions import BusinessRuleError

from .models import DeliveryTrack, Order
from .serializers import DeliverSerializer, LocationSerializer, RiderOrderSerializer


def _fresh(order_id):
    return Order.objects.select_related("shop", "track", "address").prefetch_related("items").get(pk=order_id)


class RiderOrderViewSet(ShopScopedMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """The delivery app. A rider sees only the deliveries the shop has given to them."""
    queryset = Order.objects.select_related("shop", "track", "address").prefetch_related("items")
    serializer_class = RiderOrderSerializer
    required_caps = {"*": Cap.DELIVER}

    def get_queryset(self):
        qs = super().get_queryset().filter(rider=self.request.user)
        if self.request.query_params.get("scope") == "today":
            return qs.filter(status=Order.Status.COMPLETED, updated_at__date=timezone.localdate())
        return qs.filter(status=Order.Status.OUT_FOR_DELIVERY)

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        """The rider leaves with the order. From now on the customer can follow the rider on the map."""
        order = self.get_object()
        track, _ = DeliveryTrack.objects.get_or_create(order=order)
        if track.started_at is None:
            track.started_at = timezone.now()
            track.save(update_fields=["started_at"])
            tracking_service.notify_refresh(order)
        return Response(RiderOrderSerializer(_fresh(order.pk)).data)

    @action(detail=True, methods=["post"])
    def location(self, request, pk=None):
        order = self.get_object()
        s = LocationSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        track = getattr(order, "track", None)
        if track is None or track.started_at is None:
            raise BusinessRuleError("Start the delivery first.", "trip_not_started")
        d = s.validated_data
        tracking_service.update_position(track, lat=d["lat"], lng=d["lng"], heading=d["heading"], speed=d["speed"], accuracy=d["accuracy"])
        return Response({"ok": True})

    @action(detail=True, methods=["post"])
    def arrived(self, request, pk=None):
        order = self.get_object()
        track = getattr(order, "track", None)
        if track is None or track.started_at is None:
            raise BusinessRuleError("Start the delivery first.", "trip_not_started")
        track.arrived_at = timezone.now()
        track.save(update_fields=["arrived_at"])
        tracking_service.notify_refresh(order)
        return Response(RiderOrderSerializer(_fresh(order.pk)).data)

    @action(detail=True, methods=["post"], url_path="save-location")
    def save_location(self, request, pk=None):
        """First delivery to an address with no pin: the rider, standing at the door, saves the position once."""
        order = self.get_object()
        s = LocationSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        order_service.rider_save_position(order.pk, request.shop, request.user, s.validated_data["lat"], s.validated_data["lng"])
        return Response(RiderOrderSerializer(_fresh(order.pk)).data)

    @action(detail=True, methods=["post"])
    def deliver(self, request, pk=None):
        """The customer tells the rider a 4-digit PIN from their app. Only then is the order completed."""
        order = self.get_object()
        s = DeliverSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        if order.pin_attempts >= order_service.MAX_PIN_TRIES:
            return Response({"detail": "Too many wrong PINs. Ask the shop to complete this order.", "code": "pin_locked"}, status=400)
        if not order_service.check_pin(order, s.validated_data["pin"]):
            return Response({"detail": "Wrong PIN. Ask the customer for the 4-digit PIN shown in their app.", "code": "wrong_pin"}, status=400)
        order_service.finish_delivery(order.pk, request.shop, request.user, s.validated_data["payment_method"])
        return Response(RiderOrderSerializer(_fresh(order.pk)).data)


class RiderListView(APIView):
    """The shop's delivery staff, so the shop can choose who takes an order."""
    permission_classes = [IsAuthenticated, ShopAccess]
    required_caps = {"get": Cap.MANAGE_ORDERS}

    def get(self, request):
        members = ShopMembership.objects.filter(shop=request.shop, role="delivery", is_active=True).select_related("user")
        return Response([{"id": m.user_id, "name": m.user.first_name or m.user.username, "phone": m.user.phone} for m in members])