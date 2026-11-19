import json
import uuid

from unittest.mock import MagicMock
from django.test import TestCase
from inventory.management.commands.run_eda_worker import process_storage_event
from inventory.models import Product, InventoryReservation


class StorageEDAWorkTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            sku="MOUSE-01",
            name="Mouse sem fio",
            available_quantity=10
        )

        self.mock_channel = MagicMock()
        self.mock_redis = MagicMock()

        # default: key does not exists in Redis
        self.mock_redis.exists.return_value = True


    def test_eda_order_created_successfully(self):
        """
        It must reserve inventory and publish InventoryReserved
        """
        order_uuid = uuid.uuid4()
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "OrderCreated",
            "data": {
                "order_id": str(order_uuid),
                "sku": "MOUSE-01",
                "quantity": 3
            }
        }

        result = process_storage_event(payload, self.mock_redis, self.mock_channel)

        self.assertEqual(result, "RESERVED_PUBLISHED")
        
        self.product.refresh_from_db()
        self.assertEqual(self.product.available_quantity, 7)
        self.mock_channel.basic_publish.assert_called_once()


    def test_eda_idempotency_blocks_duplicate(self):
        """
        It must ignore event if event_id already exists in Redis
        """
        # now the key exists
        self.mock_redis.exists.return_value = False 

        order_uuid = uuid.uuid4()
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "OrderCreated",
            "data": {
                "order_id": str(order_uuid),
                "sku": "MOUSE-01",
                "quantity": 3
            }
        }

        result = process_storage_event(payload, self.mock_redis, self.mock_channel)

        self.assertEqual(result, "DUPLICATE_IGNORED")
        
        # ensures that inventory has not been modified
        self.product.refresh_from_db()
        self.assertEqual(self.product.available_quantity, 10)
        self.mock_channel.basic_publish.assert_not_called()


    def test_eda_compensate_inventory_saga_rollback(self):
        """
        It must return the item to the inventory when receive CompensateInventory
        """
        order_uuid = uuid.uuid4()

        # simulate a previous reservation
        self.product.available_quantity = 8
        self.product.save()
        InventoryReservation.objects.create(
            order_id= order_uuid,
            product= self.product,
            quantity=2,
            status="RESERVED" 
        )

        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "CompensateInventory",
            "data": {"order_id": str(order_uuid)}
        }

        result = process_storage_event(payload, self.mock_redis, self.mock_channel)

        self.assertEqual(result, "COMPENSATED")

        # ensures that inventory has been updated back to the old value
        self.product.refresh_from_db()
        self.assertEqual(self.product.available_quantity, 10)

        reservation = InventoryReservation.objects.get(order_id=order_uuid)
        self.assertEqual(reservation.status, "COMPENSATED")