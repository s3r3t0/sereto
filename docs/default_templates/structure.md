# Structure

```text
├── categories/
│   └── <category>/
│       ├── findings/
│       │   └── <name>.md.j2
│       ├── skel/
│       │   ├── findings/
│       │   │   └── _base.md
│       │   ├── approach.tex.j2
│       │   └── scope.tex.j2
|       ├── finding_group.tex.j2
│       └── target.tex.j2
├── pandocfilters/
│   ├── acronyms.py
│   └── minted.py
├── plugins/
└── skel/
    ├── includes/
    |   ├── glossary.tex
    |   ├── macros.tex.j2
    |   └── sereto.cls
    ├── layouts/
    |   ├── _base.md
    |   ├── finding_group.tex.j2
    |   ├── report.tex.j2
    |   ├── sow.tex.j2
    |   └── target.tex.j2
    ├── outputs/
    ├── pictures/
    ├── .sereto
    └── .seretoignore
```


## `categories`

This directory encompasses a collection of templates for all categories of findings, such as *dast* (Dynamic Application Security Testing) and *sast* (Static Application Security Testing). Each category is represented by a dedicated directory bearing the corresponding name.

### `findings`

This directory houses the finding templates specific to the corresponding category.

### `skel`

This directory contains the skeleton files for a specific category. The contents of this directory are utilized to populate a new target directory.

- `findings`: This directory stores the finding files. Each finding is documented separately within this directory.
- `approach.tex.j2`: This file represents the approach that was used during the penetration test. It provides a detailed description of the methodology employed.
- `scope.tex.j2`: This file defines the exact scope of the penetration test for a specific target. It outlines the boundaries and limitations of the assessment.

### `finding_group.tex.j2`

This file contains the template for the finding group. It is used to group individual findings together.

### `target.tex.j2`

This file includes information such as approach, scope, and all findings associated with specific target.

## `pandocfilters`

This directory houses the pandoc filters utilized for processing the markdown files. By default, the filters `acronyms.py` and `minted.py` are employed to process the markdown files. These filters play a crucial role in enhancing the functionality and formatting of the markdown content.

## `plugins`

This directory contains an example how to define custom plugins. Plugins are used to extend the functionality of SeReTo and can be customized to suit the specific requirements of the user.

## `skel`

This directory serves as a skeleton for new projects. When creating a new project, contents of this directory are used to populate it.

For a detailed explanation of each file, please refer to the [project files](../concepts/project_files.md) section in the documentation.
