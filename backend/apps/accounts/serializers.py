from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers
from rest_framework.authtoken.models import Token

from apps.shops.models import Shop, ShopMembership
from apps.shops.roles import ROLE_CAPS
from services import subscription_service

from .models import User
from django.conf import settings

def session_payload(user):
    token, _ = Token.objects.get_or_create(user=user)
    memberships = ShopMembership.objects.select_related("shop").filter(user=user, is_active=True, shop__is_active=True)
    return {
        "token": token.key,
        "user": {"id": user.id, "username": user.username, "full_name": user.first_name,
                 "phone": user.phone, "is_staff": user.is_staff, "email": user.email,
                 "must_change_password": user.must_change_password},
        "shops": [
            {"id": m.shop_id, "name": m.shop.name, "role": m.role, "approved": m.shop.is_approved,
             "capabilities": sorted(ROLE_CAPS[m.role])}
            for m in memberships
        ],
    }


class VendorRegistrationSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, min_length=8)
    full_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=15, required=False, allow_blank=True, default="")
    shop_name = serializers.CharField(max_length=150)
    city = serializers.CharField(max_length=80, required=False, default="Etawah")
    address = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    email = serializers.EmailField(required=False, allow_blank=True, default="")

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def validate_email(self, value):
        value = value.strip().lower()
        if value and User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("This email is already used by another account.")
        return value

    def validate(self, attrs):
        try:
            validate_password(attrs["password"], user=User(username=attrs["username"]))
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)})
        return attrs

    @transaction.atomic
    def create(self, data):
        user = User.objects.create_user(
            username=data["username"], password=data["password"],
            first_name=data["full_name"], phone=data["phone"],
            email=data["email"],
        )
        approved = not getattr(settings, "NEW_SHOPS_NEED_APPROVAL", False)
        shop = Shop.objects.create(name=data["shop_name"], city=data["city"], address=data["address"],
                                   phone=data["phone"], is_approved=approved)
        ShopMembership.objects.create(user=user, shop=shop, role=ShopMembership.Role.OWNER)
        subscription_service.ensure_payment_identity(shop)
        if approved:
            subscription_service.start_trial(shop)
        return user


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()


class ResetPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField(max_length=10)
    new_password = serializers.CharField(write_only=True, min_length=8)


class ProfileSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=15, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    current_password = serializers.CharField(write_only=True, required=False, allow_blank=True)