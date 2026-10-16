from django.contrib.auth import authenticate
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .serializers import LoginSerializer, VendorRegistrationSerializer, session_payload


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
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"
    serializer_class = LoginSerializer

    def post(self, request):
        s = LoginSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = authenticate(request, username=s.validated_data["username"], password=s.validated_data["password"])
        if user is None or not user.is_active:
            return Response({"detail": "Invalid username or password."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(session_payload(user))


class MeView(APIView):
    def get(self, request):
        return Response(session_payload(request.user))


class LogoutView(APIView):
    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
