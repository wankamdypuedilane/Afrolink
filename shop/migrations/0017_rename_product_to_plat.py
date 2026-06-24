# Generated for renaming Product -> Plat (and OrderItem.product -> plat)

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0016_product_cuisinier'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='Product',
            new_name='Plat',
        ),
        migrations.RenameField(
            model_name='orderitem',
            old_name='product',
            new_name='plat',
        ),
    ]
