# Markdown building blocks

This page provides an overview of the building blocks for writing your own findings. It covers the nuances of the markdown syntax available for the default templates.

For more details about the markdown language, we recommend checking the [Markdown Guide][mdguide] and [Pandoc Flavoured Markdown][pandocmd].

!!! tip
    The public templates include a `generic/test_finding` example. You can use it as a reference and inspiration for creating your own findings.

## Text highlighting

The template supports various text highlighting options:

- **Emphasis**: Use `*` or `_` to emphasize text.
- **Strong emphasis**: Use `**` or `__` to make text bold.
- **Strike-through**: Use `~~` to strike through text.
- **Subscripts**: Use `H~2~O` to create subscripts.
- **Superscripts**: Use `x^2^` to create superscripts.
- **Underlining**: Use `[Underline this.]{.underline}` to underline text.
- **Small caps**: Use `[Small caps]{.smallcaps}` to create small caps text.

## Acronyms

Another feature of the template is the ability to define acronyms using the `[!acr]` syntax, implemented via the [pandoc filter][filter].

This feature supports both capitalization and pluralization:

- Capitalization: Use the `^` prefix, e.g., `[!^acr]`.
- Pluralization: Use the `+` prefix, e.g., `[!+acr]`.

By default, the acronym appears as `acronym (acr)` on the first occurrence and `acr` thereafter. You can explicitly set the form using the following suffixes:

- `<` for the short form
- `>` for the long form
- `!` for the full form.

??? note "Check this reference for all possible combinations."

    | Form | Tag | Display |
    | ---- | --- | ------- |
    | Default | `[!acr]` | acronym (acr) |
    | Short | `[!acr<]` | acr |
    | Long | `[!acr>]` | acronym |
    | Full | `[!acr!]` | acronym (acr) |
    | Default plural | `[!+acr]` | acrs |
    | Short plural | `[!+acr<]` | acrs |
    | Long plural | `[!+acr>]` | acronyms |
    | Full plural | `[!+acr!]` | acronyms (acrs) |
    | Default capitalized | `[!^acr]` | Acr |
    | Short capitalized | `[!^acr<]` | Acr |
    | Long capitalized | `[!^acr>]` | Acronym |
    | Full capitalized | `[!^acr!]` | Acronym (acr) |
    | Default capitalized plural | `[!+^acr]` | Acrs |
    | Short capitalized plural | `[!+^acr<]` | Acrs |
    | Long capitalized plural | `[!+^acr>]` | Acronyms |
    | Full capitalized plural | `[!+^acr!]` | Acronyms (acrs) |

## Code

Another feature implemented via the [pandoc filter][filter] is code typesetting.
Code segments are highlighted using the [pygments] library and typeset using the [fvetxra] package.
Both inline and block code segments are supported.

The language can be specified directly after the backticks (`` ` ``).

    ```py
    random.seed(42)
    print(random.random)
    ```

Alternatively, you can use the full syntax with the language specified as a dot parameter.

    ```{.py}
    random.seed(42)
    print(random.random)
    ```

## Other features

The public template is configured to support all the default [pandoc markdown][pandocmd] features. This includes:

- [Text emphasizing](#text-highlighting)
- Lists
  - Unordered
  - Ordered
  - Task
  - Definition
- Tables
- Math
- Links
- Footnotes
- Images

[mdguide]: https://www.markdownguide.org/
[pandocmd]: https://pandoc.org/MANUAL.html#pandocs-markdown
[filter]: https://pandoc.org/filters.html
[pygments]: https://pygments.org/
[fvetxra]: https://ctan.org/pkg/fvetxra
