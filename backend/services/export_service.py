import csv
import io

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


def xlsx_response(filename, header, rows):
    """Needs the openpyxl package. Text cells stay text, so barcodes keep every digit."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for row in rows:
        ws.append([c if isinstance(c, (int, float, str)) or c is None else str(c) for c in row])
    buffer = io.BytesIO()
    wb.save(buffer)
    response = HttpResponse(buffer.getvalue(),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response