"""Phase E (backend part): order lines carry the product's tiny and thumb pictures for the vendor, customer and
delivery apps (null when the product has no image). No network."""
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.catalog.models import MasterProduct
from apps.inventory.models import ShopProduct

from . import test_delivery as base   # module import: its tests are not run a second time

CLOUD = "democloud"
TINY = f"https://res.cloudinary.com/{CLOUD}/image/upload/w_120,c_limit,q_auto,f_auto/690225305747"
THUMB = f"https://res.cloudinary.com/{CLOUD}/image/upload/w_300,c_limit,q_auto,f_auto/690225305747"


@override_settings(CLOUDINARY_CLOUD_NAME=CLOUD)
class OrderLineImageTests(APITestCase):
    setUp = base.DeliveryTrackingTests.setUp
    place = base.DeliveryTrackingTests.place
    step = base.DeliveryTrackingTests.step
    send_out = base.DeliveryTrackingTests.send_out
    out_for_delivery = base.DeliveryTrackingTests.out_for_delivery

    def test_every_app_gets_line_pictures(self):
        master_id = ShopProduct.objects.get(pk=self.sp).master_product_id
        MasterProduct.objects.filter(pk=master_id).update(image="690225305747")
        oid = self.out_for_delivery()
        for client, url in ((self.v, f"{base.API}/shop/orders/{oid}/"), (self.s, f"{base.API}/store/orders/{oid}/"),
                            (self.r, f"{base.API}/delivery/orders/{oid}/")):
            line = client.get(url).data["items"][0]
            self.assertEqual((line["image_tiny"], line["image_thumb"]), (TINY, THUMB), url)

    def test_no_image_gives_null(self):
        oid = self.out_for_delivery()
        line = self.r.get(f"{base.API}/delivery/orders/{oid}/").data["items"][0]
        self.assertEqual((line["image_tiny"], line["image_thumb"]), (None, None))
