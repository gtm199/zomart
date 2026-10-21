from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower


class User(AbstractUser):
    phone = models.CharField(max_length=15, blank=True)
    must_change_password = models.BooleanField(default=False)

    class Meta(AbstractUser.Meta):
        # an email can belong to one account only (upper/lower case counts as the same); blank emails are allowed
        constraints = [models.UniqueConstraint(Lower("email"), condition=~models.Q(email=""), name="uniq_user_email_ci")]

    def __str__(self):
        return self.username


class PasswordResetCode(models.Model):
    """A code emailed to the person. Only a scrambled copy is stored."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    code_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used_at = models.DateTimeField(null=True, blank=True)
