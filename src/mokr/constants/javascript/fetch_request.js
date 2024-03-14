function (url, options) {
    var reqdata = {};
    function dump(response) {
      reqdata["headers"] = Object.fromEntries(response.headers);
      reqdata["ok"] = response.ok;
      reqdata["status"] = response.status;
      reqdata["type"] = response.type;
      reqdata["url"] = response.url;
      return response;
    };
    return fetch(url, options)
      .then(response => dump(response))
      .then(response => response.text())
      .then(text => {reqdata["body"] = text})
      .then(() => JSON.stringify(reqdata));
  }