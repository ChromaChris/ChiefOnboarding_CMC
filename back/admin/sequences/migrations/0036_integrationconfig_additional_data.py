# Generated by Django 3.2.13 on 2022-05-17 00:19

from django.db import migrations

import misc.fields


class Migration(migrations.Migration):

    dependencies = [
        ("sequences", "0035_remove_integrationconfig_additional_data"),
    ]

    operations = [
        migrations.AddField(
            model_name="integrationconfig",
            name="additional_data",
            field=misc.fields.EncryptedJSONField(default=dict),
        ),
    ]