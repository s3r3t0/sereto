# Idea

In essence, you can think about SeReTo as a comprehensive **specification** outlining the structural framework for a penetration testing **report**.

The Python package, on the other hand, is "just" the **implementation** of this specification. It provides the necessary tools to generate the report based on the specification. This setup allows for the *extensibility* of the entire solution.

The tool proves particularly useful when faced with the *frequent* creation of such reports. Additionally, when collaborating within a *team*, it ensures a *uniform* approach to reporting. SeReTo utilizes templates that may include logic to modify content based on specified variables and incorporate images, among other elements.


## Markup Language - Hybrid Approach

The initial implementation solely relied on the use of *TeX* to compose the entire content. TeX (LaTeX/XeTeX/...) is an exceptionally robust markup language that enables the creation of visually stunning documents. It enjoys widespread popularity in academic and scientific writing.

Later, we realized that composing the *entire* report in TeX was excessive. Certain sections of the report did not require the extensive expressive features of TeX and could be written in a more straightforward markup language, such as *Markdown*.

We have implemented a **hybrid** approach where the template with the overall structure of the report is composed in TeX (this is usually done *once* and does not need much work afterwards). The *findings*, on the other hand, are written in *Markdown*, allowing anyone, including *new* team members unfamiliar with TeX, to easily create reports on their own. This hybrid approach saves time and effort, while keeping the reports visually appealing.


## Templating - Jinja2

SeReTo uses the *Jinja2* templating engine to allow for the dynamic generation of the reports content. This engine is widely used in the Python community and is known for its flexibility and ease of use.

The environment for *TeX* uses the following delimiters:

- `((( ... )))` for variables
- `((* ... *))` for control structures
- `((= ... =))` for comments

The environment for *Markdown* uses the default delimiters:

- `{{ ... }}` for variables
- `{% ... %}` for control structures
- `{# ... #}` for comments
