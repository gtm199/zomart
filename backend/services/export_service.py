import csv

from django.http import HttpResponse


def csv_response(filename, header, rows):
    """UTF-8 with BOM so Excel opens Hindi/special characters correctly."""
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(header)
    writer.writerows(rows)
    return response