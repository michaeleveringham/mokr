(selectorOrXPath, isXPath, waitForVisible, waitForHidden) => {
    const node = isXPath
        ? document.evaluate(selectorOrXPath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue
        : document.querySelector(selectorOrXPath);
    if (!node)
        return waitForHidden;
    if (!waitForVisible && !waitForHidden)
        return node;
    const element = /** @type {Element} */ (node.nodeType === Node.TEXT_NODE ? node.parentElement : node);

    const style = window.getComputedStyle(element);
    const isVisible = style && style.visibility !== 'hidden' && hasVisibleBoundingBox();
    const success = (waitForVisible === isVisible || waitForHidden === !isVisible)
    return success ? node : null

    function hasVisibleBoundingBox() {
        const rect = element.getBoundingClientRect();
        return !!(rect.top || rect.bottom || rect.width || rect.height);
    }
}