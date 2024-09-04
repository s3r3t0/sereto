# Templates

```text
├── categories
│   └── <category>
│       ├── finding_group.tex.j2
│       ├── findings
│       │   └── test_finding.md.j2
│       └── skel
│           ├── approach.tex.j2
│           ├── findings
│           │   └── _base.md
│           ├── scope.tex.j2
│           └── target.tex.j2
├── pandocfilters
│   ├── acronyms.py
│   └── minted.py
└── skel
    ├── base_document.tex.j2
    ├── finding_standalone_wrapper.tex.j2
    ├── glossary.tex
    ├── macros.tex.j2
    ├── outputs
    ├── pictures
    ├── report.tex.j2
    ├── sereto.cls
    ├── sow.tex.j2
    └── target_standalone_wrapper.tex.j2
```


## `categories`

This directory encompasses a collection of templates for all categories of findings, such as *dast* (Dynamic Application Security Testing) and *sast* (Static Application Security Testing). Each category is represented by a dedicated directory bearing the corresponding name.

### `categories/<category>/finding_group.tex.j2`

This section provides the general structure for a finding group. It serves as a template for either a standalone finding or a collection of findings that should be logically interconnected.

### `categories/<category>/findings`

This directory houses the finding templates specific to the corresponding category.

### `categories/<category>/skel`

This directory contains the skeleton files for a specific category. The contents of this directory are utilized to populate a new target directory.

- `approach.tex.j2`: This file represents the approach that was used during the penetration test. It provides a detailed description of the methodology employed.
- `scope.tex.j2`: This file defines the exact scope of the penetration test for a specific target. It outlines the boundaries and limitations of the assessment.
- `target.tex.j2`: This file includes information such as approach, scope, and all findings associated with specific target.
- `findings`: This directory stores the finding files for the report project. Each finding is documented separately within this directory.


## `pandocfilters`

This directory houses the pandoc filters utilized for processing the markdown files. By default, the filters `acronyms.py` and `minted.py` are employed to process the markdown files. These filters play a crucial role in enhancing the functionality and formatting of the markdown content.


## `skel`

This directory serves as a skeleton for new report projects. When creating a new project, the contents of this directory are used to populate it.

For a detailed explanation of each file, please refer to the [project files](concepts/project_files.md) section in the documentation.
