from django.urls import path
from inventory.api import api 

urlpatterns = [
    path("api/storage/", api.urls)
]