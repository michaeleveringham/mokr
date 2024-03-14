async function waitForPredicatePageFunction(predicateBody, polling, timeout, ...args) {
    const predicate = new Function('...args', predicateBody);
    let timedOut = false;
    if (timeout)
      setTimeout(() => timedOut = true, timeout);
    if (polling === 'raf')
      return await pollRaf();
    if (polling === 'mutation')
      return await pollMutation();
    if (typeof polling === 'number')
      return await pollInterval(polling);
  
    /**
     * @return {!Promise<*>}
     */
    function pollMutation() {
      const success = predicate.apply(null, args);
      if (success)
        return Promise.resolve(success);
  
      let fulfill;
      const result = new Promise(x => fulfill = x);
      const observer = new MutationObserver(mutations => {
        if (timedOut) {
          observer.disconnect();
          fulfill();
        }
        const success = predicate.apply(null, args);
        if (success) {
          observer.disconnect();
          fulfill(success);
        }
      });
      observer.observe(document, {
        childList: true,
        subtree: true,
        attributes: true
      });
      return result;
    }
  
    /**
     * @return {!Promise<*>}
     */
    function pollRaf() {
      let fulfill;
      const result = new Promise(x => fulfill = x);
      onRaf();
      return result;
  
      function onRaf() {
        if (timedOut) {
          fulfill();
          return;
        }
        const success = predicate.apply(null, args);
        if (success)
          fulfill(success);
        else
          requestAnimationFrame(onRaf);
      }
    }
  
    /**
     * @param {number} pollInterval
     * @return {!Promise<*>}
     */
    function pollInterval(pollInterval) {
      let fulfill;
      const result = new Promise(x => fulfill = x);
      onTimeout();
      return result;
  
      function onTimeout() {
        if (timedOut) {
          fulfill();
          return;
        }
        const success = predicate.apply(null, args);
        if (success)
          fulfill(success);
        else
          setTimeout(onTimeout, pollInterval);
      }
    }
  }