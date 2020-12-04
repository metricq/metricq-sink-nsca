# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.

import pathlib
import sys

_docs_dir = pathlib.Path(__file__).resolve().parent

sys.path.insert(0, _docs_dir.parent)


# -- Project information -----------------------------------------------------

project = "MetricQ NSCA Reporter"
copyright = "2020, TU Dresden"
author = "TU Dresden"


# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosectionlabel",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "sphinx_rtd_theme",
    "sphinx_autodoc_typehints",
    "sphinxcontrib.spelling",
    "releases",
]

intersphinx_mapping = {"python": ("https://docs.python.org/3", None)}

manpages_url = "https://man7.org/linux/man-pages/man2/{page}.{section}.html"

# Add any paths that contain templates here, relative to this directory.
templates_path = ["_templates"]

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]


# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = "sphinx_rtd_theme"
html_theme_options = {"style_external_links": True}

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = []

# GitHub Pages does not serve from static directories starting with an
# underscore, but Sphinx insists on putting them into `_static`.  Adding an
# empty `.nojekyll` to the HTML root makes GitHub serve from `_static`.
html_extra_path = [".nojekyll"]

# Spelling setup
# (see https://sphinxcontrib-spelling.readthedocs.io/en/latest/customize.html)

spelling_word_list_filename = "spelling_wordlist.txt"

# Changelog generation
releases_github_path = "metricq/metricq-sink-nsca"
