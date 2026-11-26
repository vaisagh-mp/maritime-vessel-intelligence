from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("relationships", "0004_alter_vesselrelationship_role"),
    ]

    operations = [
        migrations.AddField(
            model_name="vesselrelationship",
            name="verified_by",
            field=models.ForeignKey(
                blank=True,
                help_text="The team member who confirmed this link.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="verified_relationships",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="vesselrelationship",
            name="verification_note",
            field=models.CharField(
                blank=True,
                help_text="How it was confirmed, e.g. 'Called the company, confirmed manager'.",
                max_length=300,
            ),
        ),
    ]
