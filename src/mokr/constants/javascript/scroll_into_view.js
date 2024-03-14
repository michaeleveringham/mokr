async (element, pageJavascriptEnabled) => {
    if (!element.isConnected)
        return 'Node is detached from document';
    if (element.nodeType !== Node.ELEMENT_NODE)
        return 'Node is not of type HTMLElement';
    // force-scroll if page's javascript is disabled.
    if (!pageJavascriptEnabled) {
        element.scrollIntoView({
            block: 'center',
            inline: 'center',
            behavior: 'instant',
        });
        return false;
    }
    const visibleRatio = await new Promise(resolve => {
        const observer = new IntersectionObserver(entries => {
            resolve(entries[0].intersectionRatio);
            observer.disconnect();
        });
        observer.observe(element);
    });
    if (visibleRatio !== 1.0)
        element.scrollIntoView({
            block: 'center',
            inline: 'center',
            behavior: 'instant',
        });
    return false;
}