from django.db import transaction
from rest_framework import serializers

from apps.accounts.models import User
from services import subscription_service

from .models import Shop, ShopMembership


class ShopSerializer(serializers.ModelSerializer):
    class Meta:
        model = Shop
        fields = ["id", "name", "city", "address", "phone", "gstin", "allow_negative_stock", "created_at"]
        read_only_fields = ["id", "created_at"]


class MemberSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    full_name = serializers.CharField(source="user.first_name", read_only=True)
    phone = serializers.CharField(source="user.phone", read_only=True)

    class Meta:
        model = ShopMembership
        fields = ["id", "username", "full_name", "phone", "role", "is_active"]


class MemberCreateSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, min_length=8)
    full_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=15, required=False, allow_blank=True, default="")
    role = serializers.ChoiceField(choices=[r for r in ShopMembership.Role.choices if r[0] != "owner"])

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    @transaction.atomic
    def create(self, data):
        shop = self.context["shop"]
        subscription_service.check_limit(shop, "employees")
        user = User.objects.create_user(username=data["username"], password=data["password"],
                                        first_name=data["full_name"], phone=data["phone"])
        return ShopMembership.objects.create(user=user, shop=shop, role=data["role"])


class MemberUpdateSerializer(serializers.ModelSerializer):
    role = serializers.ChoiceField(choices=[r for r in ShopMembership.Role.choices if r[0] != "owner"], required=False)

    class Meta:
        model = ShopMembership
        fields = ["role", "is_active"]
