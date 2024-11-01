# Markdown building blocks

This page provides an overview of the building blocks for writing your own findings. It covers the nuances of the markdown syntax available for the default templates.

For more details about the markdown language, we recommend checking the [Markdown Guide][mdguide] and [Pandoc Flavoured Markdown][pandocmd].

!!! tip
    The public templates include a `test_finding` example. You can use it as a reference and inspiration for creating your own findings.

## Text highlighting

The template supports various text highlighting options:

- **Emphasis**: Use `*` or `_` to emphasize text.
- **Strong emphasis**: Use `**` or `__` to make text bold.
- **Strikethrough**: Use `~~` to strike through text.
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

<details>
  <summary>
    Check this reference for all possible combinations.
  </summary>

  <table>
    <thead>
      <tr>
        <th>Form</th>
        <th>Tag</th>
        <th>Display</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>Default</td>
        <td><code>[!acr]</code></td>
        <td>acronym (acr)</td>
      </tr>
      <tr>
        <td>Short</td>
        <td><code>[!acr&lt;]</code></td>
        <td>acr</td>
      </tr>
      <tr>
        <td>Long</td>
        <td><code>[!acr&gt;]</code></td>
        <td>acronym</td>
      </tr>
      <tr>
        <td>Full</td>
        <td><code>[!acr!]</code></td>
        <td>acronym (acr)</td>
      </tr>
      <tr>
        <td>Default plural</td>
        <td><code>[!+acr]</code></td>
        <td>acrs</td>
      </tr>
      <tr>
        <td>Short plural</td>
        <td><code>[!+acr&lt;]</code></td>
        <td>acrs</td>
      </tr>
      <tr>
        <td>Long plural</td>
        <td><code>[!+acr&gt;]</code></td>
        <td>acronyms</td>
      </tr>
      <tr>
        <td>Full plural</td>
        <td><code>[!+acr!]</code></td>
        <td>acronyms (acrs)</td>
      </tr>
      <tr>
        <td>Default capitalized</td>
        <td><code>[!^acr]</code></td>
        <td>Acr</td>
      </tr>
      <tr>
        <td>Short capitalized</td>
        <td><code>[!^acr&lt;]</code></td>
        <td>Acr</td>
      </tr>
      <tr>
        <td>Long capitalized</td>
        <td><code>[!^acr&gt;]</code></td>
        <td>Acronym</td>
      </tr>
      <tr>
        <td>Full capitalized</td>
        <td><code>[!^acr!]</code></td>
        <td>Acronym (acr)</td>
      </tr>
      <tr>
        <td>Default capitalized plural</td>
        <td><code>[!+^acr]</code></td>
        <td>Acrs</td>
      </tr>
      <tr>
        <td>Short capitalized plural</td>
        <td><code>[!+^acr&lt;]</code></td>
        <td>Acrs</td>
      </tr>
      <tr>
        <td>Long capitalized plural</td>
        <td><code>[!+^acr&gt;]</code></td>
        <td>Acronyms</td>
      </tr>
      <tr>
        <td>Full capitalized plural</td>
        <td><code>[!+^acr!]</code></td>
        <td>Acronyms (acrs)</td>
      </tr>
    </tbody>
  </table>
</details>

## Code

Another feature implemented via the [pandoc filter][filter] is code typesetting.
Code segments are translated into [minted] macros, supporting both inline and block code.

The verbatim environment supports language highlighting and any [minted] attributes.
The language can be specified directly after the backticks (`` ` ``) if there are no other attributes.

``````markdown
```py
random.seed(42)
print(random.random)
```
``````

Attributes can be added after the backticks (`` ` ``) within curly braces (`{}`).
When specifying attributes, place the language as a dot parameter before other parameters.

``````markdown
```{.py linenos=true}
random.seed(42)
print(random.random)
```
``````

This extension also supports typesetting code directly from a file using the `source` attribute.

``````markdown
` `{.py source=hello.py}
``````

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
[minted]: https://ctan.org/pkg/minted
