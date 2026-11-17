from django.db import transaction 
from .models import Product, StockReservation

class OutOfStockError(Exception):
    pass 


def reserve_stock_strict(order_id:str, sku:str, quantity:int=1) -> bool:
    """
    Execute the reservation using row-level locking (select_for_update) to prevent race conditions
    when dealing with single-unit inventory
    """
    with transaction.atomic():
        product = Product.objects.select_for_update().get(sku=sku)

        if product.available_quantity < quantity:
            raise OutOfStockError(f"Estoque insuficiente para o SKU {sku}")

        product.available_quantity -= quantity
        product.save()

        StockReservation.objects.create(order_id=order_id, product=product, quantity=quantity, status=StockReservation.reserved)

        return True


def compensate_stock_sage(order_id:str) -> bool:
    """
    Compensation Action (Saga Logical Rollback)
    Returns the item to inventory if the payment subsequently fails
    """
    with transaction.atomic():
        reservation = StockReservation.objects.select_for_update().filter(order_id=order_id, status=StockReservation.reserved).first()

        if not reservation:
            return False

        product = Product.objects.select_for_update().get(sku=reservation.product.sku)
        product.available_quantity += reservation.quantity
        product.save()

        reservation.status = StockReservation.compensated
        reservation.save()

        return True