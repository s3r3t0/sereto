# Statement of Work Structure

> Keep in mind that almost anything in SeReTo can be customized to fit your needs. The following structure is the default one, but you can modify it to suit your specific requirements.

The *Statement of Work (SoW)* is a document that outlines the scope of work, deliverables, and timeline for a project. The SoW is a crucial document that helps to ensure that all parties involved in a project are on the same page regarding the project's objectives and expectations.

The **high-level overview** of the SoW document in SeReTo is defined as follows:

```text
┌───layouts/_base.tex.j2──────────────────────────────┐
│                                                     │
│ \documentclass{sereto}                              │
│                                                     │
│ \title{...}                                         │
│ \subtitle{...}                                      │
│ \author{...}                                        │
│                                                     │
│ \begin{document}                                    │
│                                                     │
│  ┌───layouts/sow.tex.j2──────────────────────────┐  │
│  │                                               │  │
│  │   Management Summary                          │  │
│  │   ...                                         │  │
│  │                                               │  │
|  ├───────────────────────────────────────────────┤  │
│  │                                               │  │
│  │   Target 1                                    │  │
│  │                                               │  │
│  │  ┌───target_<name>/scope.tex.j2───┐           │  │
│  │  └────────────────────────────────┘           │  │
│  │                                               │  │
│  │  ┌───target_<name>/approach.tex.j2───┐        │  │
│  │  └───────────────────────────────────┘        │  │
│  │                                               │  │
|  ├───────────────────────────────────────────────┤  │
│  │                                               │  │
│  │   Target 2                                    │  │
│  │   ...                                         │  │
│  │                                               │  │
│  └───────────────────────────────────────────────┘  │
│                                                     │
│ \end{document}                                      │
└─────────────────────────────────────────────────────┘
```
