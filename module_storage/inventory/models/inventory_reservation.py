from django.db import models 
from .product import Product

class InventoryReservation(models.Model):
    STATUS_CHOICES = [
        (reserved:="RESERVED", "Reservado"),
        (compensated:="COMPENSATED", "Compensado (Rollback Saga)"),
    ]

    order_id = models.UUIDField(max_length=100, unique=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.IntegerField(default=1)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=reserved)
    created_at = models.DateTimeField(auto_now_add=True)