from datetime import date

from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.shops.roles import Cap
from core.tenancy import ShopAccess, ShopScopedMixin
from services import accounting_service, export_service
from services.exceptions import BusinessRuleError

from .models import CashClose, Expense, ExpenseCategory
from .serializers import (CashCloseInputSerializer, CashCloseSerializer, ExpenseCreateSerializer,
                          ExpenseSerializer)


class ExpenseViewSet(ShopScopedMixin, mixins.CreateModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = Expense.objects.select_related("category")
    serializer_class = ExpenseSerializer
    required_caps = {"list": Cap.VIEW_REPORTS, "create": Cap.VIEW_REPORTS, "void": Cap.VIEW_REPORTS}

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("from") or p.get("to"):
            start, end = accounting_service.parse_range(p)
            qs = qs.filter(expense_date__range=(start, end))
        if p.get("category"):
            qs = qs.filter(category__name__iexact=p["category"])
        return qs

    def list(self, request, *args, **kwargs):
        if request.query_params.get("export") == "csv":
            rows = [(e.expense_date, e.category.name, e.amount, e.method, e.note, "VOID" if e.is_voided else "")
                    for e in self.get_queryset()]
            return export_service.csv_response("expenses.csv", ["date", "category", "amount", "method", "note", "status"], rows)
        return super().list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        s = ExpenseCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        name = d["category"].strip()
        category = (ExpenseCategory.objects.filter(shop=request.shop, name__iexact=name).first()
                    or ExpenseCategory.objects.create(shop=request.shop, name=name))
        expense = Expense.objects.create(shop=request.shop, category=category, amount=d["amount"], method=d["method"],
                                         expense_date=d["expense_date"] or timezone.localdate(), note=d["note"],
                                         created_by=request.user)
        return Response(ExpenseSerializer(expense).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        expense = self.get_object()
        if not expense.is_voided:
            expense.is_voided = True
            expense.save(update_fields=["is_voided"])
        return Response(ExpenseSerializer(expense).data)


class _ReportView(APIView):
    permission_classes = [IsAuthenticated, ShopAccess]
    required_caps = {"get": Cap.VIEW_REPORTS, "post": Cap.VIEW_REPORTS}


class ProfitLossView(_ReportView):
    def get(self, request):
        start, end = accounting_service.parse_range(request.query_params)
        return Response(accounting_service.profit_and_loss(request.shop, start, end))


class SalesAnalysisView(_ReportView):
    def get(self, request):
        start, end = accounting_service.parse_range(request.query_params)
        data = accounting_service.sales_analysis(request.shop, start, end)
        if request.query_params.get("export") == "csv":
            rows = [(r["product"], r["category"], r["quantity"], r["sales"], r["profit"]) for r in data["all_products"]]
            return export_service.csv_response("sales-by-product.csv", ["product", "category", "quantity", "sales", "profit"], rows)
        return Response(data)


class AgeingView(_ReportView):
    def get(self, request):
        data = accounting_service.ageing(request.shop)
        if request.query_params.get("export") == "csv":
            kind = "payables" if request.query_params.get("type") == "payables" else "receivables"
            block = data[kind]
            keys = ["balance", "0-30 days", "31-60 days", "61-90 days", "over 90 days", "unallocated"]
            rows = [[r["name"], r["phone"], *[r[k] for k in keys]] for r in block["rows"]]
            return export_service.csv_response(f"{kind}-ageing.csv", ["name", "phone", *keys], rows)
        return Response(data)


class CashCloseView(_ReportView):
    def get(self, request):
        raw = request.query_params.get("date")
        try:
            day = date.fromisoformat(raw) if raw else timezone.localdate()
        except ValueError:
            raise BusinessRuleError("Use YYYY-MM-DD for date.", "invalid_date")
        existing = CashClose.objects.filter(shop=request.shop, close_date=day).first()
        return Response({"position": accounting_service.cash_position(request.shop, day),
                         "closed": CashCloseSerializer(existing).data if existing else None})

    def post(self, request):
        s = CashCloseInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        close = accounting_service.close_day(request.shop, request.user, d["date"] or timezone.localdate(),
                                             d["counted_cash"], d["opening_cash"], d["note"])
        return Response(CashCloseSerializer(close).data, status=status.HTTP_201_CREATED)