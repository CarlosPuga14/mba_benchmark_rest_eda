import json 
import uuid

from django.test import Client, TestCase
from inventory.models import Product, StockReservation


class StorageRestApiTests(TestCase):
    def setUp(self):
        """
        Prepare initial scenary before each test
        """
        self.client = Client()
        self.url = "/api/storage/reserve"
        self.product = Product.objects.create(
            sku="NOTEBOOK-01",
            name="Notebook Gamer",
            available_quantity=5
        )

    def test_reserve_stock_success(self):
        """
        It must reserve stock and correctly decrement the available stock quantity
        """
        order_uuid = uuid.uuid4()
        paylaod = {
            "order_id": str(order_uuid),
            "sku": "NOTEBOOK-01",
            "quantity": 2
        }

        response = self.client.post(self.url, data=json.dumps(paylaod), content_type="application/json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "SUCCESS")

        # checks if the quantity in PostgreSQL database was updated to 3
        self.product.refresh_from_db()
        self.assertEqual(self.product.available_quantity, 3)

        # checks if reservation was registrated
        self.assertTrue(StockReservation.objects.filter(order_id=order_uuid, status="RESERVED").exists())


    def test_reserve_out_of_stock(self):
        """
        It must return Error 400 if the desired quantity exceds total quantity available
        """
        order_uuid = uuid.uuid4()
        payload = {
            "order_id": str(order_uuid),
            "sku": "NOTEBOOK-01",
            "quantity": 10
        }

        response = self.client.post(self.url, data=json.dumps(payload), content_type="application/json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()[ "status"], "OUT_OF_stock")

        # Ensure that original quantity has not been alterated
        self.product.refresh_from_db()
        self.assertEqual(self.product.available_quantity, 5)

    
    def test_reserve_product_not_found(self):
        """
        It must return Error 400 if SKU does not exist
        """
        order_uuid = uuid.uuid4()
        payload = {
            "order_id": str(order_uuid),
            "sku": "NOT_VALID_SKU",
            "quantity": 1
        }

        response = self.client.post(self.url, data=json.dumps(payload), content_type="application/json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["status"], "ERROR")