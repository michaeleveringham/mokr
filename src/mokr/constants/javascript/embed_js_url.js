async function addScriptUrl(url, type) {
    const script = document.createElement('script');
    script.src = url;
    if (type)
        script.type = type;
    const promise = new Promise((res, rej) => {
        script.onload = res;
        script.onerror = rej;
    });
    document.head.appendChild(script);
    await promise;
    return script;
}