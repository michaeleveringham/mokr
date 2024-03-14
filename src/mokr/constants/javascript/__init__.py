from pathlib import Path

from mokr.constants import javascript


root = Path(javascript.__file__).parent

METHOD_FOCUS_ELEMENT = 'element => element.focus()'

METHOD_GET_PROPERTY = (root / "get_property.js").read_text()
METHOD_SCROLL_INTO_VIEW = (root / "scroll_into_view.js").read_text()
METHOD_EVAL_XPATH = (root / "evaluate_xpath.js").read_text()
METHOD_ELEMENT_IN_VIEW = (root / "element_in_view.js").read_text()
METHOD_WAIT_FOR_PREDICATE_PAGE = (root / "wait_for_page.js").read_text()
METHOD_GET_CONTENT = (root / "get_content.js").read_text()
METHOD_SET_CONTENT = (root / "set_content.js").read_text()
METHOD_EMBED_JAVASCRIPT_BY_URL = (root / "embed_js_url.js").read_text()
METHOD_EMBED_JAVASCRIPT_BY_CONTENT = (root / "embed_js.js").read_text()
METHOD_EMBED_STYLE_BY_URL = (root / "embed_style_url.js").read_text()
METHOD_EMBED_STYLE_BY_CONTENT = (root / "embed_style.js").read_text()
METHOD_SELECT_VALUES = (root / "select_values.js").read_text()
METHOD_WAIT_FOR_XPATH_OR_SELECTOR = (root / "wait_for_node.js").read_text()
METHOD_ADD_PAGE_BINDING = (root / "add_binding.js").read_text()
METHOD_DELIVER_BINDING_RESULT = (root / "get_binding_result.js").read_text()
METHOD_FETCH_REQUEST = (root / "fetch_request.js").read_text()
