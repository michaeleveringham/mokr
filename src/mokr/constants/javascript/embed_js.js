function addScriptContent(content, type = 'text/javascript') {
    const script = document.createElement('script');
    script.type = type;
    script.text = content;
    let error = null;
    script.onerror = e => error = e;
    document.head.appendChild(script);
    if (error)
        throw error;
    return script;
}