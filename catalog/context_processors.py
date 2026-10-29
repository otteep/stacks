from .models import UserSettings
from .themes import get_theme


def theme(request):
    theme_id = None
    user = getattr(request, "user", None)
    if getattr(user, "is_authenticated", False):
        theme_id = (
            UserSettings.objects.filter(user_id=user.pk).values_list("theme", flat=True).first()
        )
    return {"active_theme": get_theme(theme_id)}
