# Report Structure

> Keep in mind that almost anything in SeReTo can be customized to fit your needs. The following structure is the default one, but you can modify it to suit your specific requirements.

The report is the final deliverable of a penetration test. It provides a comprehensive overview of the test's results, including the methodology, scope, and findings. The report is a crucial document that helps stakeholders understand the security posture of the tested system and make informed decisions based on the test results.

The **high-level overview** of the report document in SeReTo is defined as follows:

`target_dir` below means `target.directory_name`, the target's stable filesystem basename. For new targets it is `target_<id>` for `v1.0`, or `target_<id>_<version>`
for later versions. Legacy targets retain their existing directory names.

```text
┌───layouts/_base.tex.j2──────────────────────────────────────────────────────────────┐
│                                                                                     │
│ \documentclass{sereto}                                                              │
│                                                                                     │
│ \title{...}                                                                         │
│ \subtitle{...}                                                                      │
│ \author{...}                                                                        │
│                                                                                     │
│ \begin{document}                                                                    │
│                                                                                     │
│  ┌───layouts/report.tex.j2───────────────────────────────────────────────────────┐  │
│  │                                                                               │  │
│  │   Management Summary                                                          │  │
│  │   ...                                                                         │  │
│  │                                                                               │  │
│  │  ┌───layouts/generated/<target_dir>.tex.j2─────────────────────────────────┐  │  │
│  │  │                                                                         │  │  │
│  │  │   Target 1                                                              │  │  │
│  │  │                                                                         │  │  │
│  │  │  ┌───<target_dir>/scope.tex.j2─────┐                                    │  │  │
│  │  │  └─────────────────────────────────┘                                    │  │  │
│  │  │                                                                         │  │  │
│  │  │  ┌───<target_dir>/approach.tex.j2─────┐                                 │  │  │
│  │  │  └────────────────────────────────────┘                                 │  │  │
│  │  │                                                                         │  │  │
│  │  │   Findings                                                              │  │  │
│  │  │                                                                         │  │  │
│  │  │  ┌───layouts/generated/<target_dir>_<finding_group_uname>.tex.j2─────┐  │  │  │
│  │  │  │                                                                   │  │  │  │
│  │  │  │  ┌───<target_dir>/findings/<name>.md.j2─────┐                     │  │  │  │
│  │  │  │  └──────────────────────────────────────────┘                     │  │  │  │
│  │  │  │                                                                   │  │  │  │
│  │  │  │  ┌───<target_dir>/findings/<name>.md.j2─────┐                     │  │  │  │
│  │  │  │  └──────────────────────────────────────────┘                     │  │  │  │
│  │  │  │   ...                                                             │  │  │  │
│  │  │  └───────────────────────────────────────────────────────────────────┘  │  │  │
│  │  │                                                                         │  │  │
│  │  │  ┌───layouts/generated/<target_dir>_<finding_group_uname>.tex.j2─────┐  │  │  │
│  │  │  │                                                                   │  │  │  │
│  │  │  │  ┌───<target_dir>/findings/<name>.md.j2─────┐                     │  │  │  │
│  │  │  │  └──────────────────────────────────────────┘                     │  │  │  │
│  │  │  │                                                                   │  │  │  │
│  │  │  │  ┌───<target_dir>/findings/<name>.md.j2─────┐                     │  │  │  │
│  │  │  │  └──────────────────────────────────────────┘                     │  │  │  │
│  │  │  │   ...                                                             │  │  │  │
│  │  │  └───────────────────────────────────────────────────────────────────┘  │  │  │
│  │  │   ...                                                                   │  │  │
│  │  │                                                                         │  │  │
│  │  ├───layouts/generated/<target_dir>.tex.j2─────────────────────────────────┤  │  │
│  │  │                                                                         │  │  │
│  │  │   Target 2                                                              │  │  │
│  │  │   ...                                                                   │  │  │
│  │  │                                                                         │  │  │
│  │  └─────────────────────────────────────────────────────────────────────────┘  │  │
│  │                                                                               │  │
│  └───────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                     │
│ \end{document}                                                                      │
└─────────────────────────────────────────────────────────────────────────────────────┘
```
