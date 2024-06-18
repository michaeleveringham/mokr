project = 'mokr'
copyright = '2024, Michael Everingham'
author = 'Michael Everingham'
release = "0.1.2"

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "autoapi.extension",
    "myst_parser",
    "sphinxnotes.comboroles",
    "sphinx.ext.extlinks",
]

autoapi_dirs = ['../src']

autoapi_python_class_content = "init"

default_role = "code"

# Used for inline URLs.
extlinks = {
    'pyppeteer_url': ('https://github.com/pyppeteer/%s', '%s'),
    'puppeteer_url': ('https://github.com/puppeteer/%s', '%s'),
    'microsoft_url': ('https://github.com/microsoft/%s', '%s'),
}
comboroles_roles = {
    'pyppeteer': ['literal', 'pyppeteer_url'],
    'puppeteer': ['literal', 'puppeteer_url'],
    'microsoft': ['literal', 'microsoft_url'],
}

html_theme = 'sphinx_rtd_theme'
html_theme_options = {
    'logo_only': False,
    'display_version': True,
    'prev_next_buttons_location': 'bottom',
    'style_external_links': False,
    'vcs_pageview_mode': '',
    'style_nav_header_background': 'green',
    # Toc options
    'collapse_navigation': True,
    'sticky_navigation': True,
    'navigation_depth': 4,
    'includehidden': True,
    'titles_only': False
}

#html_static_path = ['_static']


def autoapi_skip_member(app, what, name, obj, skip, options):
    # Skip private methods.
    _name = name.split(".")[-1]
    if _name.startswith("_") and _name != "__init__":
        return True
    return None


def setup(app):
    app.connect('autoapi-skip-member', autoapi_skip_member)
