from rest_framework import serializers
from .models import User

class RegisterSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "name", "role", "api_key")
        read_only_fields = ("id", "role", "api_key")

    def create(self, validated_data):
        return User.objects.create(**validated_data)

