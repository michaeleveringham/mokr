// https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/webRequest/onAuthRequired#examples
const pendingRequests = [];

const proxyInfo = creds_placeholder;

function completed(requestDetails) {
  // A request has completed. We can stop worrying about it.
  console.log(`completed: ${requestDetails.requestId}`);
  let index = pendingRequests.indexOf(requestDetails.requestId);
  if (index > -1) {
    pendingRequests.splice(index, 1);
  }
}

function provideCredentialsAsync(requestDetails) {
  // If we have seen this request before,
  // then assume our credentials were bad,
  // and give up.
  if (pendingRequests.includes(requestDetails.requestId)) {
    console.log(`bad credentials for: ${requestDetails.requestId}`);
    return { cancel: true };
  } else {
    pendingRequests.push(requestDetails.requestId);
    console.log(`providing credentials for: ${requestDetails.requestId}`);
    // we can return a promise that will be resolved
    // with the stored credentials
    return Promise.resolve({ authCredentials: proxyInfo });
  }
}

browser.webRequest.onAuthRequired.addListener(
  provideCredentialsAsync,
  {urls: ["<all_urls>"],},
  ["blocking"],
);

browser.webRequest.onCompleted.addListener(completed, { urls: ["<all_urls>"] });

browser.webRequest.onErrorOccurred.addListener(completed, { urls: ["<all_urls>"] });