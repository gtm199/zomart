# Grocery Catalogue SaaS (Etawah kirana shops)

One central product catalogue, many independent vendor shops. Django + DRF + PostgreSQL backend, Expo (React Native, TypeScript) mobile app, Docker for the backend.

```
grocery-saas/
  backend/            Django project (config, apps, services, tests)
  mobile/             Expo app (login, billing + barcode scan, catalogue, stock, customers, today)
  docs/ARCHITECTURE.md
  docker-compose.yml          development (db + backend)
  docker-compose.prod.yml     production-style (gunicorn)
  FUTURE_FEATURES.txt         everything not built yet + known simplifications
  .env.example
```

## Honest status
The code was written and syntax-checked but **not executed** (no Django/PostgreSQL available where it was generated).
Treat the first run as verification: run the tests (step 3) and fix anything they surface before piloting.
Migrations are **not** included; step 2 generates them. Mobile package versions follow Expo SDK 57; `expo install --check` in step 6 confirms them.

## 1. Run with Docker (Windows 11, PowerShell)
Install Docker Desktop first.
```powershell
cd grocery-saas
Copy-Item .env.example .env          # then edit passwords
docker compose up --build
```
First start generates migrations into `backend\apps\*\migrations` (bind-mounted), migrates, and seeds plans.
API: http://localhost:8000/api/v1/docs/   Admin: http://localhost:8000/admin/
```powershell
docker compose exec backend python manage.py createsuperuser
```
**Commit the generated migration files**, then set `AUTO_MAKEMIGRATIONS=0` for production.

## 2. Run without Docker (PowerShell)
```powershell
cd grocery-saas\backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item ..\.env.example ..\.env
# PostgreSQL (psql as the postgres superuser):
psql -U postgres -c "CREATE USER grocery WITH PASSWORD 'change-me-db-password';"
psql -U postgres -c "CREATE DATABASE grocery_saas OWNER grocery;"
psql -U postgres -c "ALTER USER grocery CREATEDB;"   # needed so tests can create a test database
python manage.py makemigrations accounts shops subscriptions catalog inventory customers sales
python manage.py migrate
python manage.py seed_plans
python manage.py createsuperuser
python manage.py runserver 0.0.0.0:8000
```
Quick try without PostgreSQL: `$env:USE_SQLITE="1"` before the commands above.

## 3. Run the tests
```powershell
python manage.py test -v 2                                  # local
docker compose exec backend python manage.py test -v 2      # Docker
```
They cover: two vendors sharing one master product with independent price/stock, master edits not overwriting vendor data, tenant isolation (products, sales, receipts, customers), same-phone customers per vendor, immutable old invoices, idempotent checkout, stock rollback, credit ledger, returns, barcode checks, role limits, subscription read-only mode and plan limits.

## 4. Load some catalogue data
Open `/admin/` -> Master products -> add products and set **Status = active** (only active products are visible to vendors).
Or bulk import (preview first, then commit):
```powershell
docker compose exec backend python manage.py import_catalog sample_catalog.csv
docker compose exec backend python manage.py import_catalog sample_catalog.csv --commit --activate
```
The sample barcodes are test values, not real products. Verify real barcodes, MRP and tax rates yourself before use.

## 5. Try the API (PowerShell)
```powershell
$base = "http://localhost:8000/api/v1"
$r = Invoke-RestMethod -Method Post "$base/auth/register-vendor/" -ContentType "application/json" -Body '{"username":"demo","password":"Str0ngPass!42","shop_name":"Demo Kirana"}'
$h = @{ Authorization = "Token $($r.token)"; "X-Shop-ID" = "$($r.shops[0].id)" }
Invoke-RestMethod "$base/catalog/products/" -Headers $h
```

## 6. Mobile app on a physical phone (Expo SDK 57)
The app targets **Expo SDK 57** (React Native 0.86, React 19.2). Install Node.js LTS on the PC and put an Expo Go build that supports SDK 57 on the phone (same Wi-Fi as the PC).
If the store version of Expo Go has moved to a newer SDK, get the SDK 57 build from https://expo.dev/go.
```powershell
cd grocery-saas\mobile
npm install
npx expo install react-native-screens react-native-safe-area-context   # peers of expo-router, versions picked for SDK 57
npx expo install --check          # lists anything out of line with SDK 57 (add --fix to apply)
npx expo-doctor                   # optional health check
Copy-Item .env.example .env       # set EXPO_PUBLIC_API_URL to http://<your-PC-LAN-IP>:8000/api/v1  (ipconfig)
npx expo start
```
Scan the QR code with Expo Go. If the phone cannot connect, allow ports 8000 and 8081 in Windows Firewall.
Notes for SDK 57: the new architecture is the only architecture (no `newArchEnabled` key), Android is edge-to-edge, and `expo prebuild` now regenerates `android/` and `ios/` from scratch.

## 7. Production notes
```powershell
docker compose -f docker-compose.prod.yml --env-file .env up -d --build
```
Set a strong `DJANGO_SECRET_KEY`, real `DJANGO_ALLOWED_HOSTS`, put HTTPS in front, set `DJANGO_SECURE_SSL=1`, and schedule PostgreSQL backups with a tested restore.

## Roles
owner (everything) - manager (all but staff management) - cashier (sell, customers) - inventory (products/stock, sees costs) - accounts (reports, ledgers, sees costs). Send `X-Shop-ID` on every shop endpoint.
