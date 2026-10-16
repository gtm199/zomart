FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
# Windows checkouts may convert line endings; make the script safe either way.
RUN sed -i 's/\r$//' entrypoint.sh && mkdir -p /app/media /app/staticfiles

EXPOSE 8000
ENTRYPOINT ["sh", "./entrypoint.sh"]
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
