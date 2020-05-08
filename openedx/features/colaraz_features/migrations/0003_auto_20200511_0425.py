# -*- coding: utf-8 -*-
# Generated by Django 1.11.28 on 2020-05-11 08:25
from __future__ import unicode_literals

from django.db import migrations, models
import jsonfield.fields


class Migration(migrations.Migration):

    dependencies = [
        ('colaraz_features', '0002_auto_20200504_0145'),
    ]

    operations = [
        migrations.AddField(
            model_name='colarazuserprofile',
            name='role_based_urls',
            field=jsonfield.fields.JSONField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='colarazuserprofile',
            name='profile_strength_color',
            field=models.CharField(default='#A9A9A9', max_length=20),
        ),
    ]
