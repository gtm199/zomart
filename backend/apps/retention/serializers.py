from rest_framework import serializers

from .models import BillArchive, DataArchive, RetentionLog, RetentionNotice, RetentionPolicy


class PolicySerializer(serializers.ModelSerializer):
    keep_months = serializers.IntegerField(min_value=12, max_value=120)          # bill item details
    notify_days = serializers.IntegerField(min_value=7, max_value=60)
    notification_days = serializers.IntegerField(min_value=30, max_value=365)    # notifications
    audit_months = serializers.IntegerField(min_value=12, max_value=120)         # change history
    orders_months = serializers.IntegerField(min_value=6, max_value=120)         # finished online orders

    class Meta:
        model = RetentionPolicy
        fields = ["enabled", "keep_months", "notify_days", "clean_bills", "clean_notifications", "notification_days",
                  "clean_audit", "audit_months", "clean_orders", "orders_months", "last_run_on"]
        read_only_fields = ["last_run_on"]


class NoticeSerializer(serializers.ModelSerializer):
    class Meta:
        model = RetentionNotice
        fields = ["id", "category", "status", "cutoff_at", "delete_after", "bills_count", "items_count", "oldest_bill",
                  "newest_bill", "postponed_count", "created_at", "done_at"]


class ArchiveSerializer(serializers.ModelSerializer):
    class Meta:
        model = BillArchive
        fields = ["id", "period_from", "period_to", "bills_count", "items_count", "size_bytes", "created_at"]


class DataArchiveSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataArchive
        fields = ["id", "category", "period_from", "period_to", "rows_count", "detail_count", "size_bytes", "created_at"]


class LogSerializer(serializers.ModelSerializer):
    class Meta:
        model = RetentionLog
        fields = ["id", "category", "run_on", "started_at", "finished_at", "outcome", "announced_bills", "bills_archived",
                  "items_deleted", "rows_archived", "rows_deleted", "message"]