# Generated by Django 3.2.12 on 2022-04-09 17:48

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("integrations", "0013_alter_accesstoken_manifest"),
    ]

    operations = [
        migrations.AlterField(
            model_name="accesstoken",
            name="extra_args",
            field=models.JSONField(default=dict),
        ),
    ]