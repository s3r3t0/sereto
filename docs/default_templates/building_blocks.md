# Building blocks

This page provides an overview of the building blocks for creating your custom templates. See [Templating - Jinja2](../concepts/idea.md#templating-jinja2) for details on how the variables can be included in the templates.

This is so far valid for the `report.tex.j2` and `sow.tex.j2` templates.

## Variables

- `c`: The [VersionConfig](../reference/models/config.md#sereto.models.config.VersionConfig) object for the current version of the report.
- `config`: The full [Config](../reference/models/config.md#sereto.models.config.Config) object (most of the time, you should use `c` instead).
- `version`: The version of the report.
- `report_path`: Path object to the report directory.

### [VersionConfig](../reference/models/config.md#sereto.models.config.VersionConfig) variables

The attributes of the `c` object are also accessible directly. Primarily, the `c` object is used for invoking methods.

- `id`: The ID of the report.
- `name`: The name of the report.
- `targets`: List of targets.
- `dates`: List of dates.
- `people`: List of people.


## Methods for the `c` object

The following methods can be invoked from the `c` object.

Example usage:

```py
c.filter_targets(category=["dast", "sast"], name="^foo")]
c.filter_dates(type="pentest_ongoing", start="01-Jan-2024", end="31-Jan-2024")
c.filter_people(type="author", email="@foo.bar$")
```

::: sereto.models.config.VersionConfig.filter_targets
    options:
        heading_level: 3

::: sereto.models.config.VersionConfig.filter_dates
    options:
        heading_level: 3

::: sereto.models.config.VersionConfig.filter_people
    options:
        heading_level: 3
