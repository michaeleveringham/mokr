(element, expression) => {
    const document = element.ownerDocument || element;
    const iterator = document.evaluate(expression, element, null,
        XPathResult.ORDERED_NODE_ITERATOR_TYPE);
    const array = [];
    let item;
    while ((item = iterator.iterateNext()))
        array.push(item);
    return array;
}