"""Require a logged-in user for every page except the login screen.

Stacks is a private catalog, so the default is closed: a view is only
reachable anonymously if its path is listed in ``PUBLIC_PREFIXES``.
"""

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.urls import reverse

PUBLIC_PREFIXES = ("/static/", "/healthz")


class LoginRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            return self.get_response(request)

        path = request.path_info
        if path == reverse(settings.LOGIN_URL) or path.startswith(PUBLIC_PREFIXES):
            return self.get_response(request)

        # HTMX requests get a header-driven redirect instead of a login page
        # swapped into a fragment.
        if request.headers.get("HX-Request"):
            from django.http import HttpResponse

            response = HttpResponse(status=401)
            response["HX-Redirect"] = reverse(settings.LOGIN_URL)
            return response

        return redirect_to_login(request.get_full_path(), reverse(settings.LOGIN_URL))
