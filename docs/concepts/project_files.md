# Project Files

```text
├── .build/
├── includes/
├── layouts/
│   └── generated/
├── outputs/
├── pdf/
├── pictures/
├── target_<category>_<name>/
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

## `target_<category>_<name>`

Directories for a individual targets.

### `findings`

Directory for findings related to this target.

### `findings.toml`

TOML file containing metadata for the findings of this target. It is possible to define name, risk, and variables for each finding, but also to group several findings together to form a single finding group with multiple sub-findings.

## `.sereto`

Together with `config.json`, this file serves as an indicator that the current directory is a SeReTo project.

Usually, it is an empty file.

## `.seretoignore`

SeReTo offers a convenient feature that allows the inclusion of project sources in the final report PDF. This functionality utilizes the `.seretoignore` file with the same syntax as `.gitignore`, enabling the exclusion of specific files.

## `config.json`

Configuration file for the project.
