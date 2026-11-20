from django.db import models


class Payment(models.Model):
    STATUS_CHOICES = [
        (approved:="APPROVED", "Aprovado"),
        (declined:="DECLINED", "Recusado")
    ]

    order_id = models.UUIDField(unique=True, primary_key=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=approved)
    reason = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Order {self.order_id} - {self.status}"