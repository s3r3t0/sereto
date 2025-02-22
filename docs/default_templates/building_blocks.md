# Building blocks

This page provides an overview of the building blocks for creating your custom templates. See [Templating - Jinja2](../concepts/idea.md#templating-jinja2) for details on how the variables can be included in the templates.

This is so far valid for the `report.tex.j2` and `sow.tex.j2` templates.

## Variables

- `c`: The [VersionConfig](../reference/config.md#sereto.config.VersionConfig) object for the current version of the project.
- `config`: The full [Config](../reference/config.md#sereto.config.Config) object (most of the time, you should use `c` instead).
- `version`: The version of the project.
- `project_path`: Path object to the project directory.


## Useful methods and properties of the [VersionConfig](../reference/config.md#sereto.config.VersionConfig)

The following methods can be invoked from the `c` object.

Example usage:

```py
c.filter_targets(category=["dast", "sast"], name="^foo")]
c.filter_dates(type="pentest_ongoing", start="01-Jan-2024", end="31-Jan-2024")
c.filter_people(type="author", email="@foo.bar$")
```

::: sereto.config.VersionConfig.filter_targets
    options:
        heading_level: 3

::: sereto.config.VersionConfig.filter_dates
    options:
        heading_level: 3

::: sereto.config.VersionConfig.filter_people
    options:
        heading_level: 3

::: sereto.config.VersionConfig.select_target
    options:
        heading_level: 3

There are also the following properties:

::: sereto.config.VersionConfig.report_sent_date
    options:
        heading_level: 3

::: sereto.config.VersionConfig.total_open_risks
    options:
        heading_level: 3

::: sereto.config.VersionConfig.sum_risks
    options:
        heading_level: 3
