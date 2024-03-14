async function (url) {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = url;
    const promise = new Promise((res, rej) => {
        link.onload = res;
        link.onerror = rej;
    });
    document.head.appendChild(link);
    await promise;
    return link;
}