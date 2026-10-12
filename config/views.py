from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render


def home(request):
    return render(request, "home.html")


def health(request):
    """JSON endpoint the landing page calls to prove frontend <-> backend <-> DB wiring."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        db_ok = True
    except Exception:  # pragma: no cover - only hit when the DB is down
        db_ok = False
    return JsonResponse(
        {"status": "ok" if db_ok else "degraded", "database": "up" if db_ok else "down"},
        status=200 if db_ok else 503,
    )
