from django.db import migrations

FIRST = """Dear {{company_name}} team,

We understand that {{vessel_name}} (IMO {{imo}}) is expected at {{port}} on {{eta}}.

Splendour provides underwater vessel services in port. If underwater work on the vessel is of interest during this call, we would be glad to discuss how we can support you and agree a plan that fits the vessel's schedule.

Please reply to this email, or tell us who the right contact is for this vessel.

Kind regards,
{{sender_name}}
Splendour"""

REMINDER = """Dear {{company_name}} team,

A short follow-up to our earlier message about {{vessel_name}} (IMO {{imo}}), now due at {{port}} on {{eta}}.

If you would like underwater services during the call, please let us know as soon as you can so we can plan around the vessel's schedule.

Kind regards,
{{sender_name}}
Splendour"""


def add(apps, schema_editor):
    T = apps.get_model("outreach", "EmailTemplate")
    T.objects.get_or_create(
        name="First contact (72 hours before arrival)",
        defaults=dict(kind="first_contact", subject="Underwater services for {{vessel_name}} at {{port}}", body=FIRST, sort_order=10),
    )
    T.objects.get_or_create(
        name="Reminder (24 hours before arrival)",
        defaults=dict(kind="reminder", subject="Reminder: underwater services for {{vessel_name}} at {{port}}", body=REMINDER, sort_order=20),
    )


class Migration(migrations.Migration):
    dependencies = [("outreach", "0001_initial")]
    operations = [migrations.RunPython(add, migrations.RunPython.noop)]
