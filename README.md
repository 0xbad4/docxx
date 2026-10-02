# docxx

Generate C/C++ documentation from Doxygen-style comments into a JSON bundle with a minimal web viewer.

## Install

```bash
pip install docxx
```

## Quick Start

```bash
docxx include/ src/ -p "*.h;*.hpp;*.cpp"
```

Outputs `docs/docs.json` and viewer assets (`index.html`, `styles.css`, `app.js`).

## Features

- **Doxygen parsing**: Extracts `@brief`, `@details`, `@param`, `@return`, `@note`, and more
- **Markdown support**: Renders markdown in doc comments; supports `@markdown` blocks
- **Syntax highlighting**: Code blocks highlighted via Highlight.js (theme: `hjs_code_theme`)
- **Navigation**: Support for external links and embedded markdown pages in sidebar
- **Module grouping**: Group by namespace, file, or directory
- **Customizable**: Project icon, favicon, metadata, nav entries, and style themes via config

## Configuration

Edit `docs.config.json` (see `docs.config.example.json`):

- `project`: metadata dict (`name`, `brief`, `description`, `icon`, `favicon`, `nav`)
- `hjs_code_theme`: Highlight.js theme (default: `atom-one-dark`)
- `overview_file`: Path to overview/mainpage markdown
- `group_by`: Module organization (`namespace`, `file`, `dir`, `group`)

## Dependencies

**Python**:
- `python` ≥ 3.8

**Bundled in output (via CDN)**:
- `marked` - Markdown parsing and rendering
- `highlight.js` - Code syntax highlighting
- `Font Awesome 6.5.1` - Icons

## Development

```bash
pip install -e ."[test]"
pytest
```

## Live Demo

[here](https://0xbad4.github.io/docxx)

## License

MIT

