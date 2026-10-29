from django.urls import path

from . import views

urlpatterns = [
    path("", views.library, name="library"),
    path("add/", views.add_by_isbn, name="add"),
    path("add/manual/", views.add_manual, name="add_manual"),
    path("copy/<int:pk>/", views.copy_detail, name="copy_detail"),
    path("copy/<int:pk>/edit/", views.copy_edit, name="copy_edit"),
    path("copy/<int:pk>/delete/", views.copy_delete, name="copy_delete"),
    path("review/", views.review_queue, name="review"),
    path("review/<int:pk>/clear/", views.clear_review, name="clear_review"),
    path("covers/<int:book_id>/", views.cover, name="cover"),
    path("settings/", views.settings_page, name="settings"),
    path("export.csv", views.export_csv, name="export"),
    path("healthz", views.healthz, name="healthz"),
]
