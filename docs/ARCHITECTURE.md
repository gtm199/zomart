# Architecture (compact)

## A. System architecture
```
 Expo app (phone)                         Platform admin
 - camera barcode scan                    - Django admin /admin/
 - cart / bill / customers                - /api/v1/platform/catalog/*
        |  HTTPS + "Authorization: Token" + "X-Shop-ID"
        v
 +--------------------------- Django + DRF (/api/v1) ----------------------------+
 |  core.tenancy.ShopAccess  -> resolves X-Shop-ID to an ACTIVE membership,       |
 |                              checks role capability + subscription             |
 |  apps/  accounts shops subscriptions catalog inventory customers sales          |
 |  services/ billing inventory customer catalog barcode subscription receipt     |
 |            report   (all business rules; views stay thin)                       |
 +----------------------------------+---------------------------------------------+
                                    v
                              PostgreSQL 16
```

## B/C. Central catalogue vs vendor data
```
 LAYER A  (platform owned, shared)            LAYER B  (shop owned, private)
 Brand, Category                              Shop, ShopMembership, ShopSubscription
 MasterProduct --< ProductBarcode             ShopProduct  (price, cost, stock)  --> MasterProduct
 ProductChangeLog, ProductSuggestion*         StockMovement (ledger of every stock change)
                                              Customer --< CustomerLedger
                                              Sale --< SaleItem (snapshots), Payment
 * suggestion carries the shop that made it, but approval only creates a DRAFT master.
```
`MasterProduct 1 --- * ShopProduct * --- 1 Shop`, unique(shop, master_product).
Master data never stores a vendor price, cost or stock, so catalogue edits cannot overwrite them.
`SaleItem` copies name, barcode, unit price, tax rate/amount and cost at sale time, so old invoices never change.

## D. Core model definitions
See `backend/apps/catalog/models.py` (MasterProduct) and `backend/apps/inventory/models.py` (ShopProduct).

## E. Vendor / shop / membership / subscription
```
 User 1--* ShopMembership *--1 Shop 1--* ShopSubscription *--1 SubscriptionPlan
 roles: owner, manager, cashier, inventory, accounts   (capabilities in apps/shops/roles.py)
```
Registration (`POST /auth/register-vendor/`) creates user + shop + owner membership + 30-day Starter trial.

## F. Catalogue / portal API
| Method | Path | Purpose |
|---|---|---|
| GET | /catalog/categories/ | category tree |
| GET | /catalog/products/?search=&category= | browse ACTIVE master products (+ `my_listing_id`) |
| GET | /catalog/products/by-barcode/{code}/ | master lookup by barcode |
| GET | /shop/products/by-barcode/{code}/ | scan flow: master + this shop's listing |
| POST | /shop/products/ | add a master product to my shop (price, cost, opening stock) |
| PATCH | /shop/products/{id}/ | change price/cost/threshold/enabled |
| POST | /shop/products/{id}/adjust-stock/ | purchase, damage, expired, adjustment |
| POST | /shop/product-suggestions/ | suggest a missing product |
| POST | /shop/sales/ | idempotent checkout (`client_txn_id`) |
| POST | /shop/sales/{id}/return/ | return and refund |
| GET | /shop/sales/{id}/receipt/ | receipt text + wa.me link |
| GET/POST | /shop/customers/ , /{id}/receive-payment/ , /{id}/ledger/ | vendor-owned customers |
| GET | /shop/reports/daily-summary/ | daily totals |
| GET | /schema/ , /docs/ | OpenAPI + Swagger UI |

## G. Tenant isolation strategy
1. Tenant = Shop. The client sends `X-Shop-ID`; it is never trusted on its own.
2. `ShopAccess` loads the caller's ACTIVE membership for that shop. No membership -> 403.
3. `ShopScopedMixin.get_queryset()` always filters `shop=request.shop`; other shops' rows are 404.
4. Role capabilities gate each action (`required_caps`); cashiers do not see purchase costs.
5. Services always receive `shop` from the request, never from the payload; payload ids are re-checked against that shop.
6. Writes are blocked when the subscription is past its grace period; reads stay available.
7. Tests in `backend/tests/` exercise two vendors against every rule above.

## I. Phases
Built here: Phase 1 (foundation), 2 (catalogue, core), 3 (vendor portal), 4 (POS, WhatsApp share link only),
plus customer ledger and daily summary. Remaining phases: see `FUTURE_FEATURES.txt`.
