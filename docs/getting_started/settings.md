# Settings

To view the current settings, including defaults, use the command `sereto settings show`. To edit the settings in `EDITOR`, run `sereto settings edit`.

## Minimal settings

As a bare minimum, you need to specify a `projects_path` and a `templates_path`.

If you don't have the variables configured, you will be prompted to enter them when you run any command:

```
sereto new TEST
It seems like this is the first time you're running the tool. Let's set it up!

📂 Enter the path to the projects directory: /home/demo/sereto_projects
📂 Enter the path to the templates directory: /home/demo/sereto_templates
```

### `projects_path`

The path to the directory where the projects are located.

### `templates_path`

The path to the directory where the templates are located.


## Common settings

### `default_people`

Default list of people to use in new projects. Each person object may include:

::: sereto.models.person.Person
    options:
        show_root_heading: false
        show_root_toc_entry: false
        show_bases: false
        show_docstring_description: false
        show_source: false

The `type` attribute of a person can have the following values:

::: sereto.models.person.PersonType
    options:
        show_root_heading: false
        show_root_toc_entry: false
        show_bases: false
        show_docstring_description: false
        show_source: false
        docstring_section_style: list


### `plugins`

::: sereto.models.settings.Plugins
    options:
        show_root_heading: false
        show_root_toc_entry: false
        show_source: false
        show_bases: false


## Rendering settings

For rendering the documents, external commands, such as `latexmk`, are used. The sequence of commands to be used is specified in recipes.

### `render`

::: sereto.models.settings.Render
    options:
        show_root_heading: false
        show_root_toc_entry: false
        show_source: false
        show_bases: false
        members:
        - attributes


#### `tools`

List of rendering tools to be used in recipes. Each tool has the following attributes.

::: sereto.models.settings.RenderTool
    options:
        show_root_heading: false
        show_root_toc_entry: false
        show_source: false
        show_bases: false
        show_docstring_description: false
        members:
        - attributes

#### `report_recipes`, `finding_group_recipes`, `sow_recipes`, `target_recipes`

Lists of recipes to be used for reports, finding groups, SoWs and targets, respectively. Each recipe has the following attributes.

::: sereto.models.settings.RenderRecipe
    options:
        show_root_heading: false
        show_root_toc_entry: false
        show_source: false
        show_bases: false
        show_docstring_description: false
        members:
        - attributes

#### `convert_recipes`

List of recipes to be used for converting between file formats. Each recipe has the following attributes.

::: sereto.models.settings.ConvertRecipe
    options:
        show_root_heading: false
        show_root_toc_entry: false
        show_source: false
        show_bases: false
        show_docstring_description: false
        members:
        - attributes


## Other settings

### `categories`

List of categories, such as DAST, SAST, infrastructure, etc.


## Full configuration example

```json
{
  "projects_path": "/home/demo/sereto/projects",
  "templates_path": "/home/demo/sereto/templates",
  "default_people": [
    {
      "type": "author",
      "name": "John Doe",
      "business_unit": "Pentest Unit",
      "email": "john.doe@example.com",
      "role": "Penetration Tester"
    },
    {
      "type": "technical_contact",
      "name": "Jane Doe",
      "business_unit": "Pentest Unit",
      "email": "jane.doe@example.com",
      "role": "Pentest Manager"
    }
  ],
  "plugins": {
    "enabled": true,
    "directory": "/home/demo/sereto/plugins"
  }
  "render": {
    "report_recipes": [
      {
        "name": "default-report",
        "tools": [
          "latexmk"
        ]
      }
    ],
    "finding_group_recipes": [
      {
        "name": "default-finding",
        "tools": [
          "latexmk-finding"
        ]
      }
    ],
    "sow_recipes": [
      {
        "name": "default-sow",
        "tools": [
          "latexmk"
        ]
      }
    ],
    "target_recipes": [
      {
        "name": "default-target",
        "tools": [
          "latexmk-target"
        ]
      }
    ],
    "convert_recipes": [
      {
        "name": "convert-md-to-tex",
        "tools": [
          "pandoc-md"
        ],
        "input_format": "md",
        "output_format": "tex"
      }
    ],
    "tools": [
      {
        "name": "pandoc-md",
        "command": "pandoc",
        "args": [
          "--from=markdown-implicit_figures",
          "--to=latex",
          "--sandbox",
          "--filter=%TEMPLATES%/pandocfilters/acronyms.py",
          "--filter=%TEMPLATES%/pandocfilters/graphics.py",
          "--filter=%TEMPLATES%/pandocfilters/verbatim.py",
        ]
      },
      {
        "name": "latexmk",
        "command": "latexmk",
        "args": [
          "-xelatex",
          "-interaction=batchmode",
          "-halt-on-error",
          "%DOC%"
        ]
      },
      {
        "name": "latexmk-target",
        "command": "latexmk",
        "args": [
          "-xelatex",
          "-interaction=batchmode",
          "-halt-on-error",
          "%DOC%"
        ]
      },
      {
        "name": "latexmk-finding",
        "command": "latexmk",
        "args": [
          "-xelatex",
          "-interaction=batchmode",
          "-halt-on-error",
          "%DOC%"
        ]
      }
    ]
  },
  "categories": [
    "scenario",
    "mobile",
    "cicd",
    "sast",
    "rd",
    "infrastructure",
    "dast",
    "portal",
    "generic",
    "kubernetes"
  ],
  "risk_due_dates": {
    "critical": "P7D",
    "high": "P14D",
    "medium": "P30D",
    "low": "P90D"
  }
}
```
