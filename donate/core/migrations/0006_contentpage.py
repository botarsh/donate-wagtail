# Generated by Django 2.2.4 on 2019-08-23 12:10

from django.db import migrations, models
import django.db.models.deletion
import donate.core.blocks
import wagtail.core.blocks
import wagtail.core.fields
import wagtail.images.blocks


class Migration(migrations.Migration):

    dependencies = [
        ('wagtailcore', '0041_group_collection_permissions_verbose_name_plural'),
        ('core', '0005_auto_20190808_0529'),
    ]

    operations = [
        migrations.CreateModel(
            name='ContentPage',
            fields=[
                ('page_ptr', models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to='wagtailcore.Page')),
                ('call_to_action_text', models.CharField(blank=True, max_length=255)),
                ('call_to_action_url', models.URLField(blank=True)),
                ('body', wagtail.core.fields.StreamField([('heading', donate.core.blocks.HeadingBlock()), ('paragraph', wagtail.core.blocks.RichTextBlock(features=['bold', 'italic', 'ol', 'ul', 'link'])), ('image', wagtail.core.blocks.StructBlock([('image', wagtail.images.blocks.ImageChooserBlock()), ('caption', wagtail.core.blocks.CharBlock(required=False))])), ('accordion', wagtail.core.blocks.StructBlock([('title', wagtail.core.blocks.CharBlock()), ('items', wagtail.core.blocks.ListBlock(donate.core.blocks.AccordionItem))]))])),
            ],
            options={
                'abstract': False,
            },
            bases=('wagtailcore.page',),
        ),
    ]
