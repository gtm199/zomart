import uuid
from decimal import Decimal

from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import Brand, MasterProduct, ProductBarcode
from apps.shops.models import Shop, ShopMembership
from services import subscription_service

EAN_ATTA = "8901063010130"   # valid EAN-13 check digit
EAN_OIL = "8901020304050"    # valid EAN-13 check digit
EAN_BAD = "8901063010131"    # wrong check digit
API = "/api/v1"


def make_vendor(username, shop_name="Shop", role="owner", shop=None):
    user = User.objects.create_user(username, password="pass12345")
    if shop is None:
        shop = Shop.objects.create(name=shop_name)
        subscription_service.start_trial(shop)
    ShopMembership.objects.create(user=user, shop=shop, role=role)
    return user, shop


def client_for(user, shop=None):
    c = APIClient()
    c.force_authenticate(user)
    if shop is not None:
        c.credentials(HTTP_X_SHOP_ID=str(shop.id))
    return c


def make_master(name="Atta", brand="Aashirvaad", barcode=EAN_ATTA, status=MasterProduct.Status.ACTIVE,
                tax="5.00", unit="pc", pack="5"):
    brand_obj = Brand.objects.get_or_create(name=brand)[0]
    product = MasterProduct.objects.create(name=name, brand=brand_obj, status=status, tax_rate=Decimal(tax),
                                           unit=unit, pack_size=Decimal(pack))
    if barcode:
        ProductBarcode.objects.create(product=product, code=barcode, symbology="EAN13", is_primary=True)
    return product


def add_listing(client, master, price="100.00", cost="60.00", stock="10"):
    r = client.post(f"{API}/shop/products/", {"master_product": master.id, "selling_price": price,
                    "purchase_cost": cost, "opening_stock": stock}, format="json")
    assert r.status_code == 201, r.data
    return r.data


def checkout(client, sp_id, qty="2", payments=None, customer=None, txn=None, discount="0"):
    body = {
        "client_txn_id": str(txn or uuid.uuid4()),
        "items": [{"shop_product": sp_id, "quantity": qty, "discount": discount}],
        "payments": payments if payments is not None else [],
    }
    if customer:
        body["customer"] = customer
    return client.post(f"{API}/shop/sales/", body, format="json")
