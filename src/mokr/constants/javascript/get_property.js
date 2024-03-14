(object, propertyName) => {
    const result = {__proto__: null};
    result[propertyName] = object[propertyName];
    return result;
}