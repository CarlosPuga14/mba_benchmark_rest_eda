import json 
import time
import uuid 
from django.test import Client, TestCase
from billing.models import Payment


class PaymentRestApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = "/api/payment/pay"


    def test_payment_approved_success(self):
        """
        It must approve a valid payment and save it on PostgreSQL
        """
        order_uuid = uuid.uuid4()
        payload = {
            "order_id": str(order_uuid),
            "amount": "150.00"
        }

        response = self.client.post(self.url, data=json.dumps(payload), content_type="application/json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], Payment.approved)
        self.assertTrue(Payment.objects.filter(order_id=order_uuid, status=Payment.approved).exists())


    def test_payment_declined_chaos(self):
        """
        It must return HTTP 402 qhen force_decline is True
        """
        order_uuid = uuid.uuid4()

        payload = {
            "order_id": str(order_uuid),
            "amount": "150.00",
            "force_decline": True
        }

        response = self.client.post(self.url, data=json.dumps(payload), content_type="application/json")

        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.json()["status"], Payment.declined)
        self.assertTrue(Payment.objects.filter(order_id=order_uuid, status=Payment.declined).exists())


    def test_payment_simulated_latency(self):
        """
        It must respect artifical latency injected (Chaos scenario A)
        """
        payload = {
            "order_id": str(uuid.uuid4()),
            "amount": "150.00",
            "simulate_delay_ms": 200
        }

        start = time.monotonic()
        response = self.client.post(self.url, data=json.dumps(payload), content_type="application/json")
        elapsed_ms = (time.monotonic() - start) * 1000

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(elapsed_ms, 200)


    def test_payment_idempotency_same_order_id(self):
        """
        It must return a existing payment without duplicating its registry on the database
        """
        order_uuid = uuid.uuid4()
        payload = {
            "order_id": str(order_uuid),
            "amount": "150.00"
        }

        response1 = self.client.post(self.url, data=json.dumps(payload), content_type="application/json")
        response2 = self.client.post(self.url, data=json.dumps(payload), content_type="application/json")

        self.assertEqual(response1.status_code, 200)
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(Payment.objects.filter(order_id=order_uuid).count(), 1)


    def test_payment_invalid_amount_declined(self):
        """
        It must return HTTP 402 and save declination when value is 0 or less
        """
        order_uuid = uuid.uuid4()
        payload = {
            "order_id": str(order_uuid),
            "amount": "-10.00"
        }

        response = self.client.post(self.url, data=json.dumps(payload), content_type="application/json")

        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.json()["status"], Payment.declined)
        self.assertTrue(Payment.objects.filter(order_id=order_uuid, status=Payment.declined).exists())