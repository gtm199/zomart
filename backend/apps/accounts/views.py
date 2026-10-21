from rest_framework.exceptions import ValidationError
from services import password_reset_service
from .models import User
from core.throttles import LoginUsernameThrottle

from django.contrib.auth import authenticate
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .serializers import LoginSerializer, VendorRegistrationSerializer, session_payload, ForgotPasswordSerializer, ProfileSerializer, ResetPasswordSerializer

class RegisterVendorView(APIView):
    """Self-service onboarding: creates the user, the shop, the owner membership and a trial subscription."""
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"
    serializer_class = VendorRegistrationSerializer

    def post(self, request):
        s = VendorRegistrationSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = s.save()
        return Response(session_payload(user), status=status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle, LoginUsernameThrottle]
    throttle_scope = "auth"
    serializer_class = LoginSerializer

    def post(self, request):
        s = LoginSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        who = s.validated_data["username"].strip()
        # the box accepts a username or an email, in any letter case
        match = (User.objects.filter(email__iexact=who).first() if "@" in who
                 else User.objects.filter(username__iexact=who).first())
        user = authenticate(request, username=match.username if match else who, password=s.validated_data["password"])
        if user is None or not user.is_active:
            return Response({"detail": "Invalid username/email or password."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(session_payload(user))


class MeView(APIView):
    def get(self, request):
        return Response(session_payload(request.user))


class LogoutView(APIView):
    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        s = ForgotPasswordSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        password_reset_service.request_code(s.validated_data["email"])
        return Response({"detail": "If that email belongs to an account, a code has been sent. It works for 15 minutes."})


class ResetPasswordView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        s = ResetPasswordSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        password_reset_service.reset_password(d["email"], d["code"], d["new_password"])
        return Response({"detail": "Password changed. Sign in with the new password."})


class ProfileView(APIView):
    def _data(self, user):
        return {"username": user.username, "full_name": user.first_name, "phone": user.phone, "email": user.email}

    def get(self, request):
        return Response(self._data(request.user))

    def patch(self, request):
        s = ProfileSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        user = request.user
        if "email" in d:
            new = d["email"].strip().lower()
            if new != (user.email or "").lower():
                # changing the email changes who can reset the password, so the current password is required
                if not user.check_password(d.get("current_password", "")):
                    raise ValidationError({"current_password": ["Type your current password to change the email."]})
                if new and User.objects.filter(email__iexact=new).exclude(pk=user.pk).exists():
                    raise ValidationError({"email": ["This email is already used by another account."]})
                user.email = new
        if "full_name" in d:
            user.first_name = d["full_name"]
        if "phone" in d:
            user.phone = d["phone"]
        user.save()
        return Response(self._data(user))