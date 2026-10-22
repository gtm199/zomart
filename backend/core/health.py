import time
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.http import JsonResponse


def health(request):
    """Public and tiny: says only whether things work. An uptime service calls it every minute."""
    problems = []
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        problems.append("database")
    backup_dir = getattr(settings, "BACKUP_DIR", "")
    if backup_dir:
        files = sorted(Path(backup_dir).glob("db-*.sql.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
        max_hours = getattr(settings, "BACKUP_MAX_AGE_HOURS", 36)
        if not files or time.time() - files[0].stat().st_mtime > max_hours * 3600:
            problems.append("backup")
    return JsonResponse({"status": "ok" if not problems else "problem", "problems": problems},
                        status=200 if not problems else 503)