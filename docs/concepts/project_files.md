# Project Files

```text
├── .build_artifacts
├── base_document.tex.j2
├── config.json
├── finding_standalone_wrapper.tex.j2
├── glossary.tex
├── macros.tex.j2
├── pictures
│   └── logo.pdf
├── report.pdf
├── report.tex.j2
├── .sereto
├── .seretoignore
├── sow.tex.j2
├── target_<name>
│   ├── approach.tex.j2
│   ├── findings
│   │   ├── finding_<name>.tex.j2
│   │   ├── target_<name>_finding_<name>.pdf
│   │   └── <individual_finding>
│   │       └── <individual_finding>.md.j2
│   ├── findings.yaml
│   ├── risks.png
│   ├── scope.tex.j2
│   ├── screenshots
│   ├── target_dast_web1.pdf
│   └── target.tex.j2
└── target_standalone_wrapper.tex.j2
```

## `.build_artifacts`

Directory for temporary build artifacts (especially from TeX).

## `base_document.tex.j2`

Base template for TeX, which all other templates extend. This file defines the overall structure of the report (but not the content). `\begin{document}` and `\end{document}` are part of this file and therefore should not be used elsewhere.

A TeX file that uses Jinja2 templating.

## `config.json`

Configuration file for the project.

## `finding_standalone_wrapper.tex.j2`

Template for a partial report containing a single finding. This file internally includes the finding-specific content.

A TeX file that uses Jinja2 templating.

## `glossary.tex`

Definition of acronyms used in the report. We are using the `glossaries` package in TeX and an entry in this file may look like this:

```tex
\newacronym{rce}{RCE}{Remote Code Execution}
```

## `macros.tex.j2`

Custom [Jinja2 macros](https://jinja.palletsprojects.com/en/latest/templates/#macros) which simplify the writing of more complex constructs.

## `pictures`

Directory for images used in the report.

Note that there is a dedicated directory for finding screenshots in each target directory.

## `report.pdf`

The generated report PDF.

## `report.tex.j2`

Template for the final PDF report.

A TeX file that uses Jinja2 templating.

## `.sereto`

Together with `config.json`, this file serves as an indicator that the current directory is a SeReTo project.

Usually, it is an empty file.

## `.seretoignore`

SeReTo offers a convenient feature that allows the inclusion of report sources in the final report PDF. This functionality utilizes the `.seretoignore` file with the same syntax as `.gitignore`, enabling the exclusion of specific files.

## `sow.tex.j2`

Template for the Statement of Work (SoW).

A TeX file that uses Jinja2 templating.

## `target_<name>`

Directories for a individual targets.

## `target_<name>/approach.tex.j2`

Pentest approach for a specific target.

A TeX file that uses Jinja2 templating.

## `target_<name>/findings`

Directory for findings related to this target.

## `target_<name>/findings/finding_<name>.tex.j2`

Single finding group. This file internally includes the individual sub-findings.

A TeX file that uses Jinja2 templating.

## `target_<name>/findings/target_<name>_finding_<name>.pdf`

Part of the final report PDF that includes only information relevant for this finding group.

## `target_<name>/findings/<individual_finding>`

Directories for individual findings.

## `target_<name>/findings/<individual_finding>/<individual_finding>.md.j2`

The individual finding's content.

A Markdown file that uses Jinja2 templating.

## `target_<name>/findings.yaml`

YAML file containing metadata for the findings of this target. It is possible to define name, risk, and variables for each finding, but also to group several findings together to form a single finding with multiple sub-findings.

## `target_<name>/risks.png`

Generated plot summarizing the overall number of findings for each risk level.

## `target_<name>/scope.tex.j2`

Scope definition for a specific target.

A TeX file that uses Jinja2 templating.

## `target_<name>/screenshots`

Screenshots, mainly proofs for individual findings in this category.

## `target_<name>/target_<name>.pdf`

Part of the final report PDF that includes only information relevant for this target.

## `target_<name>/target.tex.j2`

Template for the report content of a specific target. This file internally includes the `approach.tex.j2`, `scope.tex.j2`, as well as the individual findings for this target.

A TeX file that uses Jinja2 templating.

## `target_standalone_wrapper.tex.j2`

Template for a partial report containing a single target. This file internally includes the `target_<name>/target.tex.j2` which contains the target-specific content.

A TeX file that uses Jinja2 templating.
