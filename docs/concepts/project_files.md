# Project Files

!!! tip
    If you are looking for explanation of the structure from the perspective of templates, please refer to the [template structure](../default_templates/structure.md) section in the documentation.

```text
├── .build/
├── includes/
├── layouts/
│   └── generated/
├── outputs/
├── pdf/
├── pictures/
├── target_<target_id>[_<version>]/
│   ├── findings/
│   │   └── <finding_name>.md.j2
│   └── findings.toml
├── .sereto
├── .seretoignore
└── config.json
```

## `.build`

Directory used for building the reports. It contains various intermediate files such as `.tex`, `.aux`, `.log`, `.toc`, and others generated during the report compilation process.

## `includes`

Directory for supplementary files that are included either through Jinja2 templating or directly in the TeX files. Examples include Jinja2 macros, the TeX glossary file, and the TeX class file (`.cls`).

## `layouts`

Directory for layout files. These files define the structure of the document.

### `generated`

Directory for generated layout files. These files are typically included in the final document from other layouts. This folder may contain layouts for each target and each finding group. Existing files are not overwritten, allowing for manual modifications.

## `outputs`

Directory for storing outputs from various tools and scripts. While SeReTo does not use this directory directly, it serves as a repository for tool outputs that are relevant to the report.

## `pdf`

Directory for the final PDF reports.

## `pictures`

Directory for images and screenshots used in the report.

## `target_<target_id>[_<version>]`

Directories for individual targets. The directory name combines the `target_`
prefix, the target's `id`, and the project version. IDs can be supplied by the user or generated automatically. IDs are unique within each configuration version. Renaming a
target does not change its ID or rename its directory. Retests preserve IDs
and copy files into separate version-suffixed directories.

The directory name is exposed as `target.directory_name` and is also used for
target-specific build paths and generated layout filenames, so customized
layouts remain in use after a display-name change.
Use `target.data.id` for selection within a version and `target.data.name` for
display labels.

Templates that previously used `target.uname` for paths must
use `target.directory_name` instead; the redundant `target.data.uname` alias
is removed in favor of `target.data.id`.
Legacy directories keep their existing names. The portion between the target_ prefix and any version suffix becomes the target’s ID — for example, target_dast_portal_v2.0 yields ID dast_portal.

### `findings`

Directory for findings related to this target.

### `findings.toml`

TOML file containing metadata for the findings of this target. It is possible to define name, risk, and variables for each finding, but also to group several findings together to form a single finding group with multiple sub-findings.

## `.sereto`

Together with `config.json`, this file serves as an indicator that the current directory is a SeReTo project.

Usually, it is an empty file.

## `.seretoignore`

SeReTo offers a convenient feature that allows the inclusion of project sources in the final report PDF. This functionality utilizes the `.seretoignore` file with the same syntax as `.gitignore`, enabling the exclusion of specific files.

For very large projects with complex ignore rules, installing the optional `performance` extra enables the `pathspec` `re2` backend when it is available.

## `config.json`

Configuration file for the project.
