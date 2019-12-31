# -*- coding: utf-8 -*-
# Generated by Django 1.11.15 on 2018-09-07 10:22
from __future__ import unicode_literals

from django.db import migrations
from django.db.models import F, Q

from pontoon.base import utils


def adjust_stats(
    self,
    total_strings_diff,
    approved_strings_diff,
    fuzzy_strings_diff,
    strings_with_errors_diff,
    strings_with_warnings_diff,
    unreviewed_strings_diff,
):
    self.total_strings = F("total_strings") + total_strings_diff
    self.approved_strings = F("approved_strings") + approved_strings_diff
    self.fuzzy_strings = F("fuzzy_strings") + fuzzy_strings_diff
    self.strings_with_errors = F("strings_with_errors") + strings_with_errors_diff
    self.strings_with_warnings = F("strings_with_warnings") + strings_with_warnings_diff
    self.unreviewed_strings = F("unreviewed_strings") + unreviewed_strings_diff

    self.save(
        update_fields=[
            "total_strings",
            "approved_strings",
            "fuzzy_strings",
            "strings_with_errors",
            "strings_with_warnings",
            "unreviewed_strings",
        ]
    )


def calculate_stats(self, apps):
    """Update stats, including denormalized ones."""
    Entity = apps.get_model("base", "Entity")
    ProjectLocale = apps.get_model("base", "ProjectLocale")
    Translation = apps.get_model("base", "Translation")

    resource = self.resource
    locale = self.locale

    entity_ids = Translation.objects.filter(locale=locale).values("entity")
    translated_entities = Entity.objects.filter(
        pk__in=entity_ids, resource=resource, obsolete=False
    )

    # Singular
    translations = Translation.objects.filter(
        entity__in=translated_entities.filter(string_plural=""), locale=locale,
    )

    approved = translations.filter(
        approved=True, errors__isnull=True, warnings__isnull=True,
    ).count()

    fuzzy = translations.filter(
        fuzzy=True, errors__isnull=True, warnings__isnull=True,
    ).count()

    errors = (
        translations.filter(
            Q(Q(Q(approved=True) | Q(fuzzy=True)) & Q(errors__isnull=False)),
        )
        .distinct()
        .count()
    )

    warnings = (
        translations.filter(
            Q(Q(Q(approved=True) | Q(fuzzy=True)) & Q(warnings__isnull=False)),
        )
        .distinct()
        .count()
    )

    unreviewed = translations.filter(
        approved=False, fuzzy=False, rejected=False,
    ).count()

    missing = resource.total_strings - approved - fuzzy - errors - warnings

    # Plural
    nplurals = len(locale.cldr_plurals.split(",")) or 1
    for e in translated_entities.exclude(string_plural="").values_list("pk"):
        translations = Translation.objects.filter(entity_id=e, locale=locale,)

        plural_approved_count = translations.filter(
            approved=True, errors__isnull=True, warnings__isnull=True,
        ).count()

        plural_fuzzy_count = translations.filter(
            fuzzy=True, errors__isnull=True, warnings__isnull=True,
        ).count()

        if plural_approved_count == nplurals:
            approved += 1
        elif plural_fuzzy_count == nplurals:
            fuzzy += 1
        else:
            plural_errors_count = (
                translations.filter(
                    Q(Q(Q(approved=True) | Q(fuzzy=True)) & Q(errors__isnull=False)),
                )
                .distinct()
                .count()
            )

            plural_warnings_count = (
                translations.filter(
                    Q(Q(Q(approved=True) | Q(fuzzy=True)) & Q(warnings__isnull=False)),
                )
                .distinct()
                .count()
            )

            if plural_errors_count:
                errors += 1
            elif plural_warnings_count:
                warnings += 1
            else:
                missing += 1

        plural_unreviewed_count = translations.filter(
            approved=False, fuzzy=False, rejected=False
        ).count()
        if plural_unreviewed_count:
            unreviewed += 1

    # Calculate diffs to reduce DB queries
    total_strings_diff = resource.total_strings - self.total_strings
    approved_strings_diff = approved - self.approved_strings
    fuzzy_strings_diff = fuzzy - self.fuzzy_strings
    strings_with_errors_diff = errors - self.strings_with_errors
    strings_with_warnings_diff = warnings - self.strings_with_warnings
    unreviewed_strings_diff = unreviewed - self.unreviewed_strings

    # Translated Resource
    adjust_stats(
        self,
        total_strings_diff,
        approved_strings_diff,
        fuzzy_strings_diff,
        strings_with_errors_diff,
        strings_with_warnings_diff,
        unreviewed_strings_diff,
    )

    # Project
    project = resource.project
    adjust_stats(
        project,
        total_strings_diff,
        approved_strings_diff,
        fuzzy_strings_diff,
        strings_with_errors_diff,
        strings_with_warnings_diff,
        unreviewed_strings_diff,
    )

    # Locale
    if not project.system_project:
        adjust_stats(
            locale,
            total_strings_diff,
            approved_strings_diff,
            fuzzy_strings_diff,
            strings_with_errors_diff,
            strings_with_warnings_diff,
            unreviewed_strings_diff,
        )

    # ProjectLocale
    project_locale = utils.get_object_or_none(
        ProjectLocale, project=project, locale=locale
    )
    if project_locale:
        adjust_stats(
            project_locale,
            total_strings_diff,
            approved_strings_diff,
            fuzzy_strings_diff,
            strings_with_errors_diff,
            strings_with_warnings_diff,
            unreviewed_strings_diff,
        )


def calculate(apps, schema_editor):
    """
    Calculate `strings_with_errors` and `strings_with_warnings`.
    """
    TranslatedResource = apps.get_model("base", "TranslatedResource")
    Translation = apps.get_model("base", "Translation")

    Error = apps.get_model("checks", "Error")
    Warning = apps.get_model("checks", "Warning")

    # Collect all translations with errors and warnings.
    translations = Translation.objects.filter(
        pk__in=(
            list(Error.objects.values_list("translation", flat=True))
            + list(Warning.objects.values_list("translation", flat=True))
        )
    ).prefetch_related("entity__resource")

    # Collect TranslatedResources of translations with errors and warnings
    # and run calculate_stats() on them.
    query = Q()
    for t in translations.values("entity__resource", "locale").distinct():
        query |= Q(resource=t["entity__resource"], locale=t["locale"])

    for tr in TranslatedResource.objects.filter(query):
        calculate_stats(tr, apps)


class Migration(migrations.Migration):

    dependencies = [
        ("base", "0132_strings_with_errors_warnings"),
        ("checks", "0003_auto_20180716_1945"),
    ]

    operations = [
        migrations.RunPython(calculate, migrations.RunPython.noop,),
    ]
