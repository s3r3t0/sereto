# Concepts

In essence, you can think about SeReTo as a comprehensive **specification** outlining the structural framework for a penetration testing **report**.

The Python package, on the other hand, is "just" the **implementation** of this specification. It provides the necessary tools to generate the report based on the specification. This setup allows for the *extensibility* of the entire solution.

The tool proves particularly useful when faced with the *frequent* creation of such reports. Additionally, when collaborating within a *team*, it ensures a *uniform* approach to reporting. SeReTo utilizes templates that may include logic to modify content based on specified variables and incorporate images, among other elements.

## Markup Language - Hybrid Approach

The initial implementation solely relied on the use of *TeX* to compose the entire content. TeX (LaTeX/XeTeX/...) is an exceptionally robust markup language that enables the creation of visually stunning documents. It enjoys widespread popularity in academic and scientific writing.

Later, we realized that composing the *entire* report in TeX was excessive. Certain sections of the report did not require the extensive expressive features of TeX and could be written in a more straightforward markup language, such as *Markdown*.

We have implemented a **hybrid** approach where the template with the overall structure of the report is composed in TeX (this is usually done *once* and does not need much work afterwards). The *findings*, on the other hand, are written in *Markdown*, allowing anyone, including *new* team members unfamiliar with TeX, to easily create reports on their own. This hybrid approach saves time and effort, while keeping the reports visually appealing.

## Report Structure

```text
├── .build_artifacts
├── config.json
├── finding.tex.j2
├── glossary.tex
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
└── target.tex.j2
```

### `.build_artifacts`

Directory for temporary build artifacts (especially from TeX).

### `config.json`

Configuration file for the project.

### `finding.tex.j2`

Template for a partial report containing a single finding. This file internally includes the finding-specific content.

A TeX file that uses Jinja2 templating.

### `glossary.tex`

Definition of acronyms used in the report. We are using the `glossaries` package in TeX and an entry in this file may look like this:

```tex
\newacronym{rce}{RCE}{Remote Code Execution}
```

### `pictures`

Directory for images used in the report.

Note that there is a dedicated directory for finding screenshots in each target directory.

### `report.pdf`

The generated report PDF.

### `report.tex.j2`

Template for the final PDF report.

A TeX file that uses Jinja2 templating.

### `.sereto`

Together with `config.json`, this file serves as an indicator that the current directory is a SeReTo project.

Usually, it is an empty file.

### `.seretoignore`

SeReTo offers a convenient feature that allows the inclusion of report sources in the final report PDF. This functionality utilizes the `.seretoignore` file with the same syntax as `.gitignore`, enabling the exclusion of specific files.

### `sow.tex.j2`

Template for the Statement of Work (SoW).

A TeX file that uses Jinja2 templating.

### `target_<name>`

Directories for a individual targets.

### `target_<name>/approach.tex.j2`

Pentest approach for a specific target.

A TeX file that uses Jinja2 templating.

### `target_<name>/findings`

Directory for findings related to this target.

### `target_<name>/findings/finding_<name>.tex.j2`

Single finding group. This file internally includes the individual sub-findings.

A TeX file that uses Jinja2 templating.

### `target_<name>/findings/target_<name>_finding_<name>.pdf`

Part of the final report PDF that includes only information relevant for this finding group.

### `target_<name>/findings/<individual_finding>`

Directories for individual findings.

### `target_<name>/findings/<individual_finding>/<individual_finding>.md.j2`

The individual finding's content.

A Markdown file that uses Jinja2 templating.

### `target_<name>/findings.yaml`

YAML file containing metadata for the findings of this target. It is possible to define name, risk, and variables for each finding, but also to group several findings together to form a single finding with multiple sub-findings.

### `target_<name>/risks.png`

Generated plot summarizing the overall number of findings for each risk level.

### `target_<name>/scope.tex.j2`

Scope definition for a specific target.

A TeX file that uses Jinja2 templating.

### `target_<name>/screenshots`

Screenshots, mainly proofs for individual findings in this category.

### `target_<name>/target_<name>.pdf`

Part of the final report PDF that includes only information relevant for this target.

### `target_<name>/target.tex.j2`

Template for the report content of a specific target. This file internally includes the `approach.tex.j2`, `scope.tex.j2`, as well as the individual findings for this target.

A TeX file that uses Jinja2 templating.

### `target_tex.j2`

Template for a partial report containing a single target. This file internally includes the `target_<name>/target.tex.j2` which contains the target-specific content.

A TeX file that uses Jinja2 templating.
