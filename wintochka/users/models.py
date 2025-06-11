from django.db import models
import uuid

class User(models.Model):
    ROLE_CHOICES = [
        ("USER", "User"),
        ("ADMIN", "Admin"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default="USER")
    api_key = models.UUIDField(default=uuid.uuid4, unique=True)

    def __str__(self):
        return f"{self.name} ({self.role})"
