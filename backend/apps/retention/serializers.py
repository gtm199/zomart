from rest_framework import serializers

from .models import BillArchive, RetentionLog, RetentionNotice, RetentionPolicy


class PolicySerializer(serializers.ModelSerializer):
    keep_months = serializers.IntegerField(min_value=12, max_value=120)
    notify_days = serializers.IntegerField(min_value=7, max_value=60)

    class Meta:
        model = RetentionPolicy
        fields = ["enabled", "keep_months", "notify_days", "last_run_on"]
        read_only_fields = ["last_run_on"]


class NoticeSerializer(serializers.ModelSerializer):
    class Meta:
        model = RetentionNotice
        fields = ["id", "status", "cutoff_at", "delete_after", "bills_count", "items_count", "oldest_bill", "newest_bill",
                  "postponed_count", "created_at", "done_at"]


class ArchiveSerializer(serializers.ModelSerializer):
    class Meta:
        model = BillArchive
        fields = ["id", "period_from", "period_to", "bills_count", "items_count", "size_bytes", "created_at"]


class LogSerializer(serializers.ModelSerializer):
    class Meta:
        model = RetentionLog
        fields = ["id", "run_on", "started_at", "finished_at", "outcome", "announced_bills", "bills_archived",
                  "items_deleted", "message"]