from django.db.models import Count, Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.catalog.models import Category, MasterProduct
from apps.inventory.models import ShopProduct
from apps.shops.models import Shop
from apps.shops.roles import Cap
from core.tenancy import ShopAccess, ShopScopedMixin
from services import order_service

from .auth import ShopperTokenAuthentication
from .models import Order, Shopper, ShopperShop, ShopperToken
from .serializers import (AcceptSerializer, CompleteSerializer, LoginSerializer, PlaceOrderSerializer,
                          PublicShopSerializer, ReasonSerializer, RegisterSerializer, ShopperOrderSerializer,
                          StoreProductSerializer, StoreSettingsSerializer, VendorOrderSerializer, clean_phone)
from .throttles import ShopperLoginThrottle


def open_shops():
    return Shop.objects.filter(store_enabled=True, is_active=True, is_approved=True)


class ShopperMixin:
    authentication_classes = [ShopperTokenAuthentication]
    permission_classes = [IsAuthenticated]


# ---------------- customer: account ----------------
def token_payload(shopper):
    token = ShopperToken.objects.create(shopper=shopper)
    for old in ShopperToken.objects.filter(shopper=shopper).order_by("-created_at")[5:]:  # keep the latest 5 phones
        old.delete()
    return {"token": token.key, "shopper": {"id": shopper.id, "name": shopper.name, "phone": shopper.phone}}


class ShopperRegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        s = RegisterSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        shopper = Shopper(name=s.validated_data["name"].strip(), phone=s.validated_data["phone"])
        shopper.set_password(s.validated_data["password"])
        shopper.save()
        return Response(token_payload(shopper), status=status.HTTP_201_CREATED)


class ShopperLoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle, ShopperLoginThrottle]
    throttle_scope = "auth"

    def post(self, request):
        s = LoginSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        shopper = Shopper.objects.filter(phone=clean_phone(s.validated_data["phone"]), is_active=True).first()
        if shopper is None or not shopper.check_password(s.validated_data["password"]):
            return Response({"detail": "Wrong mobile number or password."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(token_payload(shopper))


class ShopperMeView(ShopperMixin, APIView):
    def get(self, request):
        s = request.user
        return Response({"id": s.id, "name": s.name, "phone": s.phone})


class ShopperLogoutView(ShopperMixin, APIView):
    def post(self, request):
        request.auth.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------- customer: shops and products ----------------
class ShopListView(ShopperMixin, ListAPIView):
    serializer_class = PublicShopSerializer
    pagination_class = None

    def get_queryset(self):
        qs = open_shops().order_by("name")
        p = self.request.query_params
        if p.get("code"):
            return qs.filter(store_code=p["code"].strip().upper())
        if p.get("search"):
            term = p["search"].strip()
            qs = qs.filter(Q(name__icontains=term) | Q(city__icontains=term) | Q(address__icontains=term))
        return qs[:30]


class ShopDetailView(ShopperMixin, RetrieveAPIView):
    serializer_class = PublicShopSerializer

    def get_queryset(self):
        return open_shops()


class MyShopsView(ShopperMixin, APIView):
    def get(self, request):
        shops = open_shops().filter(pk__in=ShopperShop.objects.filter(shopper=request.user).values("shop_id"))
        return Response(PublicShopSerializer(shops, many=True).data)

    def post(self, request):
        shop_id = request.data.get("shop")
        shop = open_shops().filter(pk=shop_id).first() if str(shop_id).isdigit() else None
        if shop is None:
            raise NotFound("Shop not found.")
        ShopperShop.objects.get_or_create(shopper=request.user, shop=shop)
        return Response(PublicShopSerializer(shop).data, status=status.HTTP_201_CREATED)

    def delete(self, request):
        ShopperShop.objects.filter(shopper=request.user, shop_id=request.data.get("shop")).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


def _shop_or_404(shop_id):
    shop = open_shops().filter(pk=shop_id).first()
    if shop is None:
        raise NotFound("This shop is not available.")
    return shop


def _visible_products(shop):
    return (ShopProduct.objects.filter(shop=shop, is_enabled=True, online_visible=True,
                                       master_product__status=MasterProduct.Status.ACTIVE)
            .select_related("master_product__category", "shop"))


class StoreProductsView(ShopperMixin, ListAPIView):
    serializer_class = StoreProductSerializer

    def get_queryset(self):
        qs = _visible_products(_shop_or_404(self.kwargs["shop_id"])).order_by("master_product__name")
        p = self.request.query_params
        term = (p.get("search") or "").strip()
        if term:
            qs = qs.filter(Q(master_product__name__icontains=term) | Q(master_product__brand__name__icontains=term) |
                           Q(master_product__search_keywords__icontains=term))
        cat = p.get("category")
        if cat and cat.isdigit():
            qs = qs.filter(Q(master_product__category_id=cat) | Q(master_product__category__parent_id=cat))
        return qs


class StoreCategoriesView(ShopperMixin, APIView):
    def get(self, request, shop_id):
        base = _visible_products(_shop_or_404(shop_id))
        counts = dict(base.values_list("master_product__category").annotate(n=Count("id")))
        rows = [{"id": c.id, "name": c.name, "parent": c.parent_id, "sort_order": c.sort_order,
                 "product_count": counts.get(c.id, 0)} for c in Category.objects.all()]
        return Response(rows)


# ---------------- customer: orders ----------------
class ShopperOrderViewSet(ShopperMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                          viewsets.GenericViewSet):
    serializer_class = ShopperOrderSerializer

    def get_queryset(self):
        return Order.objects.filter(shopper=self.request.user).select_related("shop").prefetch_related("items", "events")

    def create(self, request, *args, **kwargs):
        s = PlaceOrderSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        order, created = order_service.place_order(
            shopper=request.user, shop_id=d["shop"], items=d["items"], fulfilment=d["fulfilment"],
            address=d["address"], note=d["note"], payment_method=d["payment_method"], client_txn_id=d["client_txn_id"])
        order = self.get_queryset().get(pk=order.pk)
        return Response(ShopperOrderSerializer(order).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        order = self.get_object()
        order_service.customer_cancel(order.pk, request.user)
        return Response(ShopperOrderSerializer(self.get_queryset().get(pk=order.pk)).data)


# ---------------- shop: orders ----------------
class OrderViewSet(ShopScopedMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = Order.objects.prefetch_related("items", "events").select_related("shop")
    serializer_class = VendorOrderSerializer
    required_caps = {"*": Cap.MANAGE_ORDERS}

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("scope") == "active":
            qs = qs.filter(status__in=order_service.ACTIVE)
        elif p.get("scope") == "past":
            qs = qs.exclude(status__in=order_service.ACTIVE)
        if p.get("search"):
            term = p["search"].strip().lstrip("#")
            cond = Q(customer_name__icontains=term) | Q(customer_phone__contains=term)
            if term.isdigit():
                cond |= Q(number=int(term))
            qs = qs.filter(cond)
        return qs

    def _out(self, order):
        return Response(VendorOrderSerializer(self.get_queryset().get(pk=order.pk)).data)

    @action(detail=False)
    def summary(self, request):
        qs = Order.objects.filter(shop=request.shop)
        return Response({"new": qs.filter(status=Order.Status.PLACED).count(),
                         "active": qs.filter(status__in=order_service.ACTIVE).count()})

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        s = AcceptSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(order_service.accept(self.get_object().pk, request.shop, s.validated_data["items"]))

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        s = ReasonSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(order_service.move(self.get_object().pk, request.shop, Order.Status.REJECTED, s.validated_data["reason"]))

    @action(detail=True, methods=["post"])
    def pack(self, request, pk=None):
        return self._out(order_service.move(self.get_object().pk, request.shop, Order.Status.PACKED))

    @action(detail=True, methods=["post"])
    def ready(self, request, pk=None):
        """Packed order goes out for delivery, or waits at the counter for pickup."""
        order = self.get_object()
        step = (Order.Status.OUT_FOR_DELIVERY if order.fulfilment == Order.Fulfilment.DELIVERY
                else Order.Status.READY_FOR_PICKUP)
        return self._out(order_service.move(order.pk, request.shop, step))

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        s = CompleteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(order_service.complete(self.get_object().pk, request.shop, request.user, s.validated_data["payment_method"]))

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        s = ReasonSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(order_service.move(self.get_object().pk, request.shop, Order.Status.CANCELLED, s.validated_data["reason"]))


class StoreSettingsView(APIView):
    permission_classes = [IsAuthenticated, ShopAccess]
    required_caps = {"get": Cap.MANAGE_SHOP, "patch": Cap.MANAGE_SHOP}

    def _data(self, shop):
        data = StoreSettingsSerializer(shop).data
        data["share_text"] = (f"Order from {shop.name} on your phone. Install the Kirana Orders app and enter "
                              f"shop code {shop.store_code}.") if shop.store_code else ""
        return data

    def get(self, request):
        return Response(self._data(request.shop))

    def patch(self, request):
        shop = request.shop
        s = StoreSettingsSerializer(shop, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        if shop.store_enabled:
            order_service.ensure_store_code(shop)
        return Response(self._data(shop))