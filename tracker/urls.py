from django.urls import path
from . import views

urlpatterns = [
    path("healthz/", views.health, name="health"),
    path("month-review/", views.month_review, name="month_review"),
    path("bank-tally/", views.bank_tally, name="bank_tally"),
    path("reports/", views.monthly_reports, name="monthly_reports"),
    path("stock/<int:pk>/reverse/", views.stock_reverse, name="stock_reverse"),
    path("", views.dashboard, name="dashboard"),
    path("transactions/", views.transactions, name="transactions"),
    path("transactions/new/<str:kind>/", views.entry_form, name="entry_add"),
    path("transactions/<int:pk>/edit/", views.entry_form, name="entry_edit"),
    path("transactions/<int:pk>/void/", views.entry_void, name="entry_void"),
    path("products/", views.products, name="products"),
    path("products/new/", views.product_form, name="product_add"),
    path("products/<int:pk>/", views.product_detail, name="product_detail"),
    path("products/<int:pk>/edit/", views.product_form, name="product_edit"),
    path("products/<int:pk>/stock/", views.stock_form, name="stock_add"),
    path("settings/", views.workspace_settings, name="settings"),
    path("history/", views.history, name="history"),
    path("export/", views.export_csv, name="export_csv"),
]
