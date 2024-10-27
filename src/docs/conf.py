# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information
from __future__ import annotations

import sys
from importlib.metadata import distribution
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib as toml
else:
    import tomli as toml


conf = Path(__file__).resolve()
sys.path.insert(0, str(conf.parent.parent))
pyproject = conf.parent.parent.with_name("pyproject.toml")
with pyproject.open("rb") as f:
    pyproject_dict = toml.load(f)

project = pyproject_dict["project"]["name"]
dist = distribution(project)
author = "Choi Min-yeong"
copyright = "2024, Choi Min-yeong"
release = dist.version
repo_url: str = pyproject_dict["project"]["urls"]["Source"]

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx_autodoc_typehints",
    "sphinx_immaterial",
    "sphinx_immaterial.task_lists",
]

templates_path = ["_templates"]
exclude_patterns = []


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "sphinx_immaterial"
html_static_path = ["_static"]
html_theme_options = {
    "repo_url": repo_url,
    "repo_name": repo_url.removeprefix("https://github.com/"),
    "icon": {"repo": "fontawesome/brands/github", "edit": "material/file-edit-outline"},
    "features": [
        "navigation.tabs",
        "navigation.tabs.sticky",
        "navigation.top",
        "navigation.tracking",
        "search.highlight",
        "toc.follow",
    ],
    "palette": [
        {
            "media": "(prefers-color-scheme)",
            "toggle": {
                "icon": "material/brightness-auto",
                "name": "Switch to light mode",
            },
        },
        {
            "media": "(prefers-color-scheme: light)",
            "scheme": "default",
            "toggle": {"icon": "material/brightness-7", "name": "Switch to dark mode"},
        },
        {
            "media": "(prefers-color-scheme: dark)",
            "scheme": "slate",
            "toggle": {
                "icon": "material/brightness-4",
                "name": "Switch to system preference",
            },
        },
    ],
}
### sphinx.ext.autodoc
autodoc_class_signature = "mixed"
autodoc_member_order = "bysource"
autodoc_docstring_signature = True
autodoc_typehints = "both"
autodoc_typehints_description_target = "all"
autodoc_typehints_format = "short"
### sphinx.ext.napoleon
napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = False
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = True
napoleon_use_admonition_for_notes = True
napoleon_use_admonition_for_references = True
napoleon_use_ivar = False
napoleon_use_param = True
napoleon_use_rtype = True
napoleon_preprocess_types = True
napoleon_type_aliases = None
napoleon_attr_annotations = True
### autodoc-typehints
typehints_fully_qualified = False
always_document_param_types = False
always_use_bars_union = False
typehints_document_rtype = True
typehints_use_rtype = True
typehints_defaults = "braces"
simplify_optional_unions = True
typehints_formatter = None
typehints_use_signature = True
typehints_use_signature_return = True
### myst-parser
myst_gfm_only = True
