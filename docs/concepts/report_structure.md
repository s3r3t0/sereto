# Report Structure

> Keep in mind that almost anything in SeReTo can be customized to fit your needs. The following structure is the default one, but you can modify it to suit your specific requirements.

The report is the final deliverable of a penetration test. It provides a comprehensive overview of the test's results, including the methodology, scope, and findings. The report is a crucial document that helps stakeholders understand the security posture of the tested system and make informed decisions based on the test results.

The **high-level overview** of the report document in SeReTo is defined as follows:

```text
┌───base_document.tex.j2────────────────────────────────────────────────────┐
│                                                                           │
│ \documentclass{sereto}                                                    │
│                                                                           │
│ \title{...}                                                               │
│ \subtitle{...}                                                            │
│ \author{...}                                                              │
│                                                                           │
│ \begin{document}                                                          │
│                                                                           │
│  ┌───report.tex.j2─────────────────────────────────────────────────────┐  │
│  │                                                                     │  │
│  │   Management Summary                                                │  │
│  │   ...                                                               │  │
│  │                                                                     │  │
│  │  ┌───target_<name>/target.tex.j2─────────────────────────────────┐  │  │
│  │  │                                                               │  │  │
│  │  │   Target 1                                                    │  │  │
│  │  │                                                               │  │  │
│  │  │  ┌───target_<name>/scope.tex.j2───┐                           │  │  │
│  │  │  └────────────────────────────────┘                           │  │  │
│  │  │                                                               │  │  │
│  │  │  ┌───target_<name>/approach.tex.j2───┐                        │  │  │
│  │  │  └───────────────────────────────────┘                        │  │  │
│  │  │                                                               │  │  │
│  │  │   Findings                                                    │  │  │
│  │  │                                                               │  │  │
│  │  │  ┌───target_<name>/findings/<finding_group_uname>.tex.j2───┐  │  │  │
│  │  │  │                                                         │  │  │  │
│  │  │  │  ┌───target_<name>/findings/<name>/<name>.md.j2───┐     │  │  │  │
│  │  │  │  └────────────────────────────────────────────────┘     │  │  │  │
│  │  │  │                                                         │  │  │  │
│  │  │  │  ┌───target_<name>/findings/<name>/<name>.md.j2───┐     │  │  │  │
│  │  │  │  └────────────────────────────────────────────────┘     │  │  │  │
│  │  │  │   ...                                                   │  │  │  │
│  │  │  └─────────────────────────────────────────────────────────┘  │  │  │
│  │  │                                                               │  │  │
│  │  │  ┌───target_<name>/findings/<finding_group_uname>.tex.j2───┐  │  │  │
│  │  │  │                                                         │  │  │  │
│  │  │  │  ┌───target_<name>/findings/<name>/<name>.md.j2───┐     │  │  │  │
│  │  │  │  └────────────────────────────────────────────────┘     │  │  │  │
│  │  │  │                                                         │  │  │  │
│  │  │  │  ┌───target_<name>/findings/<name>/<name>.md.j2───┐     │  │  │  │
│  │  │  │  └────────────────────────────────────────────────┘     │  │  │  │
│  │  │  │   ...                                                   │  │  │  │
│  │  │  └─────────────────────────────────────────────────────────┘  │  │  │
│  │  │   ...                                                         │  │  │
│  │  │                                                               │  │  │
│  │  │───target_<name>/target.tex.j2─────────────────────────────────│  │  │
│  │  │                                                               │  │  │
│  │  │   Target 2                                                    │  │  │
│  │  │   ...                                                         │  │  │
│  │  │                                                               │  │  │
│  │  └───────────────────────────────────────────────────────────────┘  │  │
│  │                                                                     │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                           │
│ \end{document}                                                            │
└───────────────────────────────────────────────────────────────────────────┘
```
