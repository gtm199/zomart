from django.db.models.signals import pre_save
from django.dispatch import receiver
from rest_framework.authtoken.models import Token

from .models import User


@receiver(pre_save, sender=User)
def sign_out_everywhere_when_password_changes(sender, instance, **kwargs):
    """Whoever changes a password (admin, owner, the person themself): old phones lose access at once."""
    if instance.pk is None:
        return
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and "password" not in update_fields:
        return
    old = User.objects.filter(pk=instance.pk).values_list("password", flat=True).first()
    if old is not None and old != instance.password:
        Token.objects.filter(user_id=instance.pk).delete()