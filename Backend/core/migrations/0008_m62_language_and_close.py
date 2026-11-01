# Generated for Milestone 6.2 language fields and user-closed browser flag.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0007_agenttask_needs_grounded_answer"),
    ]

    operations = [
        migrations.AddField(
            model_name="browsersession",
            name="browser_closed_by_user",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="agenttask",
            name="goal_original",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="agenttask",
            name="language",
            field=models.CharField(max_length=8, default="en"),
        ),
    ]
