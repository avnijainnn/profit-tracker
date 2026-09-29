from datetime import date
from decimal import Decimal
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from tracker.forms import StockForm
from tracker.models import Account, Category, Entry, InventoryLot, Product, StockMovement
from tracker.services import add_stock, product_stats, report, setup_defaults


class ReceiptRegressionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('receipt-review')
        setup_defaults(cls.user)
        cls.bank = Account.objects.get(owner=cls.user, name='Bank 1')
        cls.category = Category.objects.get(owner=cls.user, name='Manufacturing')
        cls.product = Product.objects.create(owner=cls.user, sku='REVIEW', name='Review bag')

    def receipt(self, **overrides):
        values = dict(date=date(2025, 8, 1), kind='received', quantity=4,
                      manufacturing_cost=Decimal('100.00'), payment_account=self.bank,
                      costs_confirmed=True, submission_token=uuid.uuid4())
        values.update(overrides)
        return values

    def test_missing_receipt_date_returns_validation_error(self):
        form = StockForm({'kind': 'received', 'date': '', 'quantity': 1,
                          'costs_confirmed': 'on', 'submission_token': uuid.uuid4()},
                         owner=self.user, product=self.product, action='received')
        self.assertFalse(form.is_valid())
        self.assertIn('date', form.errors)

    def test_receipt_retry_checks_costs_and_account(self):
        values = self.receipt()
        first = add_stock(self.product, self.user, values)
        self.assertEqual(add_stock(self.product, self.user, values).pk, first.pk)
        for changes in ({'manufacturing_cost': Decimal('200.00')},
                        {'payment_account': Account.objects.get(owner=self.user, name='Cash')},
                        {'payment_date': date(2025, 7, 31)}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                add_stock(self.product, self.user, {**values, **changes})
        self.assertEqual(InventoryLot.objects.count(), 1)
        self.assertEqual(Entry.objects.count(), 1)

    def test_stale_expense_cannot_be_capitalized_twice(self):
        expense = Entry.objects.create(owner=self.user, product=self.product, kind='expense',
            date=date(2025, 7, 1), amount=Decimal('100.00'), account=self.bank, category=self.category)
        values = self.receipt(manufacturing_cost=Decimal('0.00'), existing_cost_entries=[expense])
        add_stock(self.product, self.user, values)
        with self.assertRaises(ValidationError):
            add_stock(self.product, self.user, {**values, 'submission_token': uuid.uuid4()})
        self.assertEqual(InventoryLot.objects.count(), 1)

    def test_remaining_lots_follow_sale_then_damage_chronology(self):
        a = add_stock(self.product, self.user, self.receipt())
        b = add_stock(self.product, self.user, self.receipt(date=date(2025, 8, 2)))
        for day, kind, qty in ((3, 'sold', 5), (4, 'damaged', 2)):
            add_stock(self.product, self.user, dict(date=date(2025, 8, day), kind=kind, quantity=qty))
        stats = product_stats(self.product, date(2025, 8, 1), date(2025, 9, 1))
        self.assertEqual(stats['available'], 1)
        self.assertEqual({r['lot'].pk: r['remaining'] for r in stats['lots']},
                         {a.inventory_lot_id: 0, b.inventory_lot_id: 1})

    def test_lot_view_preserves_paise_and_excludes_capitalized_expenses(self):
        add_stock(self.product, self.user, self.receipt(extra_shipping_cost=Decimal('1.25'),
                                                       other_direct_cost=Decimal('2.50')))
        self.client.force_login(self.user)
        response = self.client.get(reverse('product_detail', args=[self.product.pk]))
        self.assertContains(response, '3.75')
        self.assertEqual(list(response.context['expenses']), [])

    def test_incomplete_costs_and_sales_are_flagged_in_affected_months(self):
        add_stock(self.product, self.user, self.receipt(manufacturing_cost=Decimal("0.00"), costs_confirmed=False))
        add_stock(self.product, self.user, dict(date=date(2025, 8, 2), kind="damaged", quantity=1))
        Entry.objects.create(owner=self.user, kind="income", date=date(2025, 9, 1),
            sale_date=date(2025, 8, 3), amount=Decimal("500.00"), source="upi", account=self.bank)
        august = report(self.user, date(2025, 8, 1), date(2025, 9, 1))["totals"]
        self.assertEqual(august["writeoff_unknown_units"], 1)
        self.assertEqual(august["unrecognized_receipts"], 1)
