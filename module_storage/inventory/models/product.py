from django.db import models

class Product(models.Model):
    sku = models.CharField(max_length=50, unique=True, primary_key=True)
    name = models.CharField(max_length=150)
    available_quantity = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.sku} - Qtd: {self.available_quantity}"