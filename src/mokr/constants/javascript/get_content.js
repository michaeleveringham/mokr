() => {
    let retVal = '';
    if (document.doctype)
      retVal = new XMLSerializer().serializeToString(document.doctype);
    if (document.documentElement)
      retVal += document.documentElement.outerHTML;
    return retVal;
  }