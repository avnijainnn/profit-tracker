from datetime import date
from decimal import Decimal
from io import BytesIO
import tempfile
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from tracker.models import Account, Category, Entry, Product, StockMovement, StockReversal
from tracker.services import add_stock, edit_stock, product_stats, report, setup_defaults, stock_state


class SimpleWorkspaceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('simple-owner')
        self.other = get_user_model().objects.create_user('other-owner')
        setup_defaults(self.user)
        self.bank = Account.objects.get(owner=self.user, name='Bank 1')
        self.category = Category.objects.get(owner=self.user, name='Manufacturing')
        self.product = Product.objects.create(owner=self.user, name='Pastel tote', sku='PASTEL')
        self.client.force_login(self.user)

    def expense(self, **overrides):
        return Entry.objects.create(owner=self.user, kind='expense', date=date(2025, 8, 20),
            amount=Decimal('1234.50'), account=self.bank, category=self.category,
            product=self.product, **overrides)

    def receipt(self, quantity=10):
        return add_stock(self.product, self.user, {'date': date(2025, 9, 3), 'kind': 'received',
            'quantity': quantity, 'batch_name': 'September', 'notes': '', 'submission_token': uuid.uuid4()})

    def test_receiving_stock_keeps_august_payment_out_of_september(self):
        expense = self.expense()
        url = reverse('stock_add', args=[self.product.pk]) + '?action=received'
        response = self.client.post(url, {'date': '2025-09-03', 'quantity': 10,
            'batch_name': 'September', 'submission_token': uuid.uuid4()})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Entry.objects.count(), 1)
        august = report(self.user, date(2025, 8, 1), date(2025, 9, 1))['totals']
        september = report(self.user, date(2025, 9, 1), date(2025, 10, 1))['totals']
        self.assertEqual(august['expense'], Decimal('1234.50'))
        self.assertEqual(september['expense'], 0)
        for month, expected in [('2025-08', [expense]), ('2025-09', [])]:
            page = self.client.get(reverse('product_detail', args=[self.product.pk]), {'month': month})
            self.assertEqual(list(page.context['expenses']), expected)
            self.assertNotContains(page, 'Cost status')
            self.assertNotContains(page, 'More stock actions')

    def test_profit_matches_received_money_minus_all_expenses(self):
        third_party = Account.objects.get(owner=self.user, name='Paid by someone else')
        Entry.objects.create(owner=self.user, kind='income', date=date(2025, 8, 1),
            amount=1000, source='cash', account=self.bank)
        self.expense()
        Entry.objects.create(owner=self.user, kind='expense', date=date(2025, 8, 22),
            amount=100, account=third_party, category=self.category, paid_by='Owner')
        page = self.client.get(reverse('dashboard'), {'month': '2025-08'})
        self.assertEqual(page.context['totals']['result'], Decimal('-334.50'))
        self.assertEqual(len(page.context['page']), 3)
        self.assertNotContains(page, 'Operating Profit')
        self.assertNotContains(page, 'Source breakdown')
        self.assertNotContains(page, 'Units sold this month')
        form = self.client.get(reverse('entry_add', args=['income']))
        self.assertNotContains(form, 'name="sale_date"')
        self.assertNotContains(form, 'name="recognized_amount"')

    def test_expense_edit_and_delete_apply_to_totals_and_audit_once(self):
        entry = self.expense()
        edit = self.client.post(reverse('entry_edit', args=[entry.pk]), {
            'date': '2025-08-20', 'amount': '900.25', 'account': self.bank.pk,
            'category': self.category.pk, 'product': self.product.pk,
            'expected_revision': entry.revision, 'submission_token': uuid.uuid4()})
        self.assertEqual(edit.status_code, 302)
        entry.refresh_from_db()
        self.assertEqual(entry.amount, Decimal('900.25'))
        payload = {'expected_revision': entry.revision, 'submission_token': uuid.uuid4()}
        url = reverse('entry_delete', args=[entry.pk])
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        entry.refresh_from_db()
        self.assertIsNotNone(entry.voided_at)
        self.assertEqual(report(self.user, date(2025, 8, 1), date(2025, 9, 1))['totals']['expense'], 0)
        self.assertEqual(self.user.changelog_set.filter(action='entry_voided').count(), 1)

    def test_legacy_lot_payment_can_be_edited_and_deleted(self):
        movement = add_stock(self.product, self.user, {'date': date(2025, 9, 1), 'kind': 'received',
            'quantity': 10, 'manufacturing_cost': 100, 'payment_account': self.bank,
            'payment_date': date(2025, 8, 20), 'costs_confirmed': True})
        entry = Entry.objects.get()
        self.assertTrue(entry.capitalized_inventory_cost)
        response = self.client.post(reverse('entry_edit', args=[entry.pk]), {
            'date': '2025-08-20', 'amount': '110', 'account': self.bank.pk,
            'category': entry.category_id, 'product': self.product.pk,
            'expected_revision': entry.revision, 'submission_token': uuid.uuid4()})
        self.assertEqual(response.status_code, 302)
        entry.refresh_from_db()
        response = self.client.post(reverse('entry_delete', args=[entry.pk]), {
            'expected_revision': entry.revision, 'submission_token': uuid.uuid4()})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(StockMovement.objects.get(pk=movement.pk).quantity, 10)

    def test_stock_edit_changes_quantity_without_moving_payment(self):
        self.expense()
        movement = self.receipt()
        response = self.client.post(reverse('stock_edit', args=[movement.pk]), {
            'date': '2025-09-05', 'quantity': 12, 'batch_name': 'Corrected', 'notes': '',
            'expected_state': stock_state(movement), 'submission_token': uuid.uuid4()})
        self.assertEqual(response.status_code, 302)
        movement.refresh_from_db()
        self.assertEqual(movement.quantity, 12)
        self.assertEqual(movement.inventory_lot.quantity_received, 12)
        self.assertEqual(movement.inventory_lot.received_date, date(2025, 9, 5))
        self.assertEqual(Entry.objects.get().date, date(2025, 8, 20))
        self.assertEqual(Entry.objects.count(), 1)

    def test_stock_edit_and_delete_cannot_make_stock_negative(self):
        movement = self.receipt()
        add_stock(self.product, self.user, {'date': date(2025, 9, 4), 'kind': 'sold', 'quantity': 5})
        old_state = stock_state(movement)
        with self.assertRaises(ValidationError):
            edit_stock(movement, self.user, {'date': movement.date, 'quantity': 4, 'batch_name': '',
                'notes': '', 'expected_state': old_state, 'submission_token': uuid.uuid4()})
        response = self.client.post(reverse('stock_delete', args=[movement.pk]), {
            'expected_state': old_state, 'submission_token': uuid.uuid4()})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'later stock movements depend')
        self.assertFalse(StockReversal.objects.exists())
        self.assertEqual(product_stats(self.product, date(2025, 9, 1), date(2025, 10, 1))['available'], 5)

    def test_stock_delete_replay_and_owner_boundaries(self):
        movement = self.receipt()
        url = reverse('stock_delete', args=[movement.pk])
        payload = {'expected_state': stock_state(movement), 'submission_token': uuid.uuid4()}
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertEqual(StockReversal.objects.count(), 1)
        self.client.force_login(self.other)
        for route, pk in [('stock_edit', movement.pk), ('stock_delete', movement.pk),
                          ('product_photo', self.product.pk)]:
            self.assertEqual(self.client.get(reverse(route, args=[pk])).status_code, 404)

    def test_photo_upload_display_replacement_and_removal(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            def photo(color):
                buf = BytesIO()
                Image.new('RGB', (32, 32), color).save(buf, format='PNG')
                return SimpleUploadedFile('tote.png', buf.getvalue(), content_type='image/png')
            url = reverse('product_edit', args=[self.product.pk])
            data = {'sku': self.product.sku, 'name': self.product.name, 'kind': 'bag', 'active': 'on'}
            self.assertEqual(self.client.post(url, {**data, 'photo': photo('pink')}).status_code, 302)
            self.product.refresh_from_db()
            first_name = self.product.photo.name
            self.assertTrue(first_name.endswith('.jpg'))
            photo_url = reverse('product_photo', args=[self.product.pk])
            page = self.client.get(reverse('products'))
            self.assertContains(page, photo_url)
            image_response = self.client.get(photo_url)
            self.assertEqual(image_response.status_code, 200)
            self.assertEqual(image_response['Content-Type'], 'image/jpeg')
            image_response.close()
            self.client.force_login(self.other)
            self.assertEqual(self.client.get(photo_url).status_code, 404)
            self.client.logout()
            self.assertEqual(self.client.get(photo_url).status_code, 302)
            self.client.force_login(self.user)
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.client.post(url, {**data, 'photo': photo('green')}).status_code, 302)
            self.product.refresh_from_db()
            self.assertNotEqual(first_name, self.product.photo.name)
            self.assertFalse(self.product.photo.storage.exists(first_name))
            replacement_name = self.product.photo.name
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.client.post(url, {**data, 'photo-clear': 'on'}).status_code, 302)
            self.product.refresh_from_db()
            self.assertFalse(self.product.photo)
            self.assertFalse(self.product.photo.storage.exists(replacement_name))

    def test_invalid_photo_does_not_save_product(self):
        response = self.client.post(reverse('product_edit', args=[self.product.pk]), {
            'sku': self.product.sku, 'name': 'Must not save', 'kind': 'bag',
            'photo': SimpleUploadedFile('fake.jpg', b'not an image', content_type='image/jpeg')})
        self.assertEqual(response.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, 'Pastel tote')
