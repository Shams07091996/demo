"""Hotel stays and transfers: one price -> cost (what we pay) and revenue (what we get).

The old price becomes the cost and its currency is used for both sides; revenue starts empty.
"""

from django.db import migrations, models


def currency_for_both_sides(apps, schema_editor):
    for name in ("HotelStay", "Transfer"):
        model = apps.get_model("sheet", name)
        for booking in model.objects.all():
            booking.revenue_currency = booking.cost_currency
            booking.save(update_fields=["revenue_currency"])


CURRENCY_CHOICES = [("EGP", "EGP"), ("USD", "USD")]


class Migration(migrations.Migration):
    dependencies = [("sheet", "0007_transfer_airport_and_port")]

    operations = [
        migrations.RenameField("hotelstay", "price_per_night", "cost_per_night"),
        migrations.RenameField("hotelstay", "currency", "cost_currency"),
        migrations.AddField(
            "hotelstay", "revenue_per_night",
            models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            "hotelstay", "revenue_currency", models.CharField(choices=CURRENCY_CHOICES, default="EGP", max_length=3)
        ),
        migrations.RenameField("transfer", "price", "cost"),
        migrations.RenameField("transfer", "currency", "cost_currency"),
        migrations.AddField(
            "transfer", "revenue", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)
        ),
        migrations.AddField(
            "transfer", "revenue_currency", models.CharField(choices=CURRENCY_CHOICES, default="EGP", max_length=3)
        ),
        migrations.RunPython(currency_for_both_sides, migrations.RunPython.noop),
    ]
