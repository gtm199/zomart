from django.test import TestCase
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.catalog.models import Brand, Category, MasterProduct
from apps.inventory.models import ShopProduct
from services import catalog_import_service as imp
from services import catalog_service
from services.exceptions import BusinessRuleError

from .helpers import API, EAN_ATTA, EAN_BAD, EAN_OIL, add_listing, checkout, client_for, make_master, make_vendor


def staff(name, superuser=False):
    return User.objects.create_user(name, password="x", is_staff=True, is_superuser=superuser)


class ApprovalAndVerificationTests(APITestCase):
    def setUp(self):
        self.editor, self.approver = staff("editor"), staff("approver", superuser=True)
        self.product = make_master(status=MasterProduct.Status.DRAFT)
        self.url = f"{API}/platform/catalog/products/{self.product.id}"

    def test_editor_cannot_activate_but_approver_can(self):
        e, a = client_for(self.editor), client_for(self.approver)
        r = e.post(f"{self.url}/activate/")
        self.assertEqual((r.status_code, r.data["code"]), (403, "approval_required"))
        r = e.patch(f"{self.url}/", {"status": "active"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(e.patch(f"{self.url}/", {"description": "ok"}, format="json").status_code, 200)
        self.assertEqual(a.post(f"{self.url}/activate/").status_code, 200)

    def test_changing_mrp_clears_verification_other_edits_do_not(self):
        a = client_for(self.approver)
        a.patch(f"{self.url}/", {"mrp": "100.00"}, format="json")
        self.assertEqual(a.post(f"{self.url}/verify/", {"source": "pack"}, format="json").status_code, 200)
        a.patch(f"{self.url}/", {"description": "new text"}, format="json")
        self.product.refresh_from_db()
        self.assertIsNotNone(self.product.mrp_verified_at)
        a.patch(f"{self.url}/", {"mrp": "110.00"}, format="json")
        self.product.refresh_from_db()
        self.assertIsNone(self.product.mrp_verified_at)
        self.assertEqual(a.post(f"{self.url}/verify/", {"source": "nonsense"}, format="json").status_code, 400)


class DeactivationNoticeTests(APITestCase):
    def test_only_shops_that_stock_the_product_are_told(self):
        product = make_master()
        ua, shop_a = make_vendor("n_a", "Shop A")
        ub, shop_b = make_vendor("n_b", "Shop B")
        uc, shop_c = make_vendor("n_c", "Shop C")
        a, b, c = client_for(ua, shop_a), client_for(ub, shop_b), client_for(uc, shop_c)
        add_listing(a, product)
        add_listing(b, product)
        client_for(staff("boss", True)).post(f"{API}/platform/catalog/products/{product.id}/deactivate/")
        self.assertEqual(a.get(f"{API}/shop/notifications/").data["unread_count"], 1)
        self.assertEqual(b.get(f"{API}/shop/notifications/").data["unread_count"], 1)
        self.assertEqual(c.get(f"{API}/shop/notifications/").data["unread_count"], 0)
        listing = a.get(f"{API}/shop/products/").data["results"][0]
        self.assertFalse(listing["master_active"])
        a.post(f"{API}/shop/notifications/")
        self.assertEqual(a.get(f"{API}/shop/notifications/").data["unread_count"], 0)
        self.assertEqual(b.get(f"{API}/shop/notifications/").data["unread_count"], 1)  # B's notice is B's own


class MergeTests(TestCase):
    def test_merge_moves_shops_and_barcodes_and_keeps_history(self):
        dup = make_master("Atta dup", barcode=EAN_OIL)
        keep = make_master("Atta", barcode=EAN_ATTA)
        u, shop = make_vendor("m_owner", "Merge Shop")
        c = client_for(u, shop)
        sp = add_listing(c, dup, stock="5")["id"]
        sale = checkout(c, sp, qty="1", payments=[{"method": "cash", "amount": "100.00"}]).data
        preview = catalog_service.merge_products(dup.id, keep.id)
        self.assertEqual(preview["shops_moved"], 1)
        dup.refresh_from_db()
        self.assertNotEqual(dup.status, MasterProduct.Status.INACTIVE)  # preview changed nothing
        catalog_service.merge_products(dup.id, keep.id, commit=True)
        dup.refresh_from_db()
        self.assertEqual((dup.status, dup.merged_into_id), (MasterProduct.Status.INACTIVE, keep.id))
        self.assertEqual(ShopProduct.objects.get(pk=sp).master_product_id, keep.id)
        self.assertEqual({b.code for b in keep.barcodes.all()}, {EAN_ATTA, EAN_OIL})
        after = c.get(f"{API}/shop/sales/{sale['id']}/").data
        self.assertIn("Atta dup", after["items"][0]["product_name"])  # the old bill still says what was sold

    def test_merge_is_refused_when_one_shop_stocks_both(self):
        dup, keep = make_master("A1", barcode=EAN_OIL), make_master("A2", barcode=EAN_ATTA)
        u, shop = make_vendor("m_both", "Both Shop")
        c = client_for(u, shop)
        add_listing(c, dup)
        add_listing(c, keep)
        with self.assertRaises(BusinessRuleError):
            catalog_service.merge_products(dup.id, keep.id, commit=True)
        self.assertEqual(ShopProduct.objects.filter(master_product=dup).count(), 1)

    def test_brand_and_category_merge(self):
        b1, b2 = Brand.objects.create(name="Tata"), Brand.objects.create(name="TATA Salt")
        MasterProduct.objects.create(name="Salt", brand=b1, unit="kg")
        catalog_service.merge_brands(b1.id, b2.id, commit=True)
        self.assertEqual(MasterProduct.objects.get(name="Salt").brand_id, b2.id)
        self.assertFalse(Brand.objects.filter(pk=b1.pk).exists())
        c1, c2 = Category.objects.create(name="Oil"), Category.objects.create(name="Cooking oils")
        child = Category.objects.create(name="Mustard", parent=c1)
        catalog_service.merge_categories(c1.id, c2.id, commit=True)
        child.refresh_from_db()
        self.assertEqual(child.parent_id, c2.id)
        with self.assertRaises(BusinessRuleError):
            catalog_service.merge_categories(c2.id, child.id)  # target sits inside the source


class ImportServiceTests(TestCase):
    def test_validation_catches_the_usual_mistakes(self):
        make_master("Existing", brand="Acme", barcode=EAN_ATTA, pack="1", unit="kg")
        rows = [
            {"name": "Good Dal", "brand": "Acme", "pack_size": "1", "unit": "kg", "barcode": EAN_OIL},
            {"name": "Bad check digit", "unit": "kg", "barcode": EAN_BAD},
            {"name": "Barcode taken", "unit": "kg", "barcode": EAN_ATTA},
            {"name": "Wrong unit", "unit": "boxes"},
            {"name": "Existing", "brand": "Acme", "pack_size": "1", "unit": "kg"},
            {"name": "Good Dal", "brand": "Acme", "pack_size": "1", "unit": "kg"},
            {"name": "Bad tax", "unit": "pc", "tax_rate": "500"},
        ]
        good, errors = imp.validate_rows(rows)
        self.assertEqual([g["name"] for g in good], ["Good Dal"])
        self.assertEqual(len(errors), 6)
        self.assertTrue(any("conflict" in e and "already on product" in e for e in errors))
        self.assertEqual(imp.commit_rows(good), 1)
        self.assertEqual(MasterProduct.objects.get(name="Good Dal").status, MasterProduct.Status.DRAFT)

    def test_export_can_be_imported_again(self):
        make_master("Round Trip", barcode=EAN_OIL, pack="2", unit="kg")
        header, rows = imp.export_rows(MasterProduct.objects.all())
        self.assertEqual(header[:6], ["name", "brand", "category", "pack_size", "unit", "barcode"])
        self.assertEqual(rows[0][5], EAN_OIL)