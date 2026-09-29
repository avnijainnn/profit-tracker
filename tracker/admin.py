"""Read-only records in admin: write via app forms so validation/auditing is kept."""
from django.contrib import admin
from .models import (Account, BankTally, Category, ChangeLog, Entry, Product, StockMovement,
                     StockReversal, MonthReview, Submission, InventoryLot, LotDepletion, Subcategory)


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False
    def has_delete_permission(self, request, obj=None):
        return False
    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(Entry)
class EntryAdmin(ReadOnlyAdmin):
    list_display = ("date", "owner", "kind", "amount", "account", "voided_at")
    list_filter = ("kind", "date", "owner")
    search_fields = ("reference", "notes")


for model in (Account, BankTally, Category, Subcategory, Product, InventoryLot, StockMovement,
              LotDepletion, ChangeLog, StockReversal, MonthReview, Submission):
    admin.site.register(model, ReadOnlyAdmin)
admin.site.site_header = "Profit Studio · maintenance"
