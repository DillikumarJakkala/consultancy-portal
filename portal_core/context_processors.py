from .models import Notification


def subvendor_notifications(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {
            "subvendor_unread_notifications": [],
            "subvendor_unread_count": 0,
        }
    qs = Notification.objects.filter(recipient=user, is_read=False)
    return {
        "subvendor_unread_notifications": qs[:10],
        "subvendor_unread_count": qs.count(),
    }
