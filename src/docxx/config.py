"""The default configuration dict (docs.config.json shape)."""

DEFAULT_CONFIG = {
    "project": {},                    # -> output "metadata": {name, version, author, repo, description, ...}
                                       # viewer-specific keys also supported here:
                                       #   title   - browser tab/page title (defaults to name)
                                       #   favicon - URL or data-URI for the browser favicon
                                       #   nav     - list of extra nav-menu items:
                                       #             [{"label": "GitHub", "url": "...", "icon": "github", "type": "external"}]
                                       #             [{"label": "Changelog", "url": "./CHANGELOG.md", "type": "markdown"}]
    "input": [],
    "patterns": ["*.h", "*.hpp", "*.hh", "*.hxx", "*.cpp", "*.cc", "*.cxx"],
    "exclude_files": [],
    "exclude": ["*::detail::*", "detail::*", "*::impl::*", "impl::*",
                "*::internal::*", "internal::*"],
    "access": ["public"],
    "include_undocumented": True,
    "undocumented_macros": False,
    "group_by": "namespace",          # namespace | group | file | dir
    "root_namespace": "",             # stripped before choosing the module
    "strip_macros": [],               # e.g. ["LC3_API", "EXPORT"] removed from declarations
    "source_url": "",                 # per-item URL template: {file} and {line} are substituted.
                                       # e.g. https://github.com/u/r/blob/main/{file}#L{line}
    "source_base": "",               # base URL for source file links used by the viewer.
                                       # e.g. https://github.com/u/r/blob/main/
                                       # Written into metadata.source_base in the output JSON.
    "header_exts": [".h", ".hpp", ".hh", ".hxx", ".h++", ".inl", ".ipp", ".tpp"],
    "overview_file": "",              # path to a plain-text file of Doxygen-style content (@brief, @note, ...)
                                       # for the overview page — see README "overview file" section.
    "module_order": [],
    "modules": {},                    # per-module overrides, keyed by the computed module key:
                                       # {"vm": {"name": "VM", "brief": "..."}}
    "overrides": {},
    # Viewer customization: highlight.js theme for code blocks (default),
    # and a top-left project icon (URL or data URI) shown above the title.
    "hjs_code_theme": "atom-one-dark",
    # Project-level metadata may include an "icon" key which the viewer
    # will render above the project name when present.
}
