from django.db import transaction 
from uuid import UUID

from .models import Product, InventoryReservation

class OutOfinventoryError(Exception):
    pass 


def reserve_inventory_strict(order_id:UUID, sku:str, quantity:int=1) -> bool:
    """
    Execute the reservation using row-level locking (select_for_update) to prevent race conditions
    when dealing with single-unit inventory
    """
    with transaction.atomic():
        product = Product.objects.select_for_update().get(sku=sku)

        if product.available_quantity < quantity:
            raise OutOfinventoryError(f"Estoque insuficiente para o SKU {sku}")

        product.available_quantity -= quantity
        product.save()

        InventoryReservation.objects.create(order_id=order_id, product=product, quantity=quantity, status=InventoryReservation.reserved)

        return True


def compensate_inventory_sage(order_id:UUID) -> bool:
    """
    Compensation Action (Saga Logical Rollback)
    Returns the item to inventory if the payment subsequently fails
    """
    with transaction.atomic():
        reservation = InventoryReservation.objects.select_for_update().filter(order_id=order_id, status=InventoryReservation.reserved).first()

        if not reservation:
            return False

        product = Product.objects.select_for_update().get(sku=reservation.product.sku)
        product.available_quantity += reservation.quantity
        product.save()

        reservation.status = InventoryReservation.compensated
        reservation.save()

        return True