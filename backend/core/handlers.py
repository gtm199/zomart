from rest_framework.response import Response
from rest_framework.views import exception_handler

from services.exceptions import BusinessRuleError


def api_exception_handler(exc, context):
    if isinstance(exc, BusinessRuleError):
        return Response({"detail": exc.message, "code": exc.code}, status=exc.status_code)
    return exception_handler(exc, context)
