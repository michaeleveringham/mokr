async function (content) {
    const style = document.createElement('style');
    style.type = 'text/css';
    style.appendChild(document.createTextNode(content));
    const promise = new Promise((res, rej) => {
        style.onload = res;
        style.onerror = rej;
    });
    document.head.appendChild(style);
    await promise;
    return style;
}