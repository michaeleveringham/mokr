function addPageBinding(bindingName) {
    const binding = window[bindingName];
    window[bindingName] = async(...args) => {
      const me = window[bindingName];
      let callbacks = me['callbacks'];
      if (!callbacks) {
        callbacks = new Map();
        me['callbacks'] = callbacks;
      }
      const seq = (me['lastSeq'] || 0) + 1;
      me['lastSeq'] = seq;
      const promise = new Promise(fulfill => callbacks.set(seq, fulfill));
      binding(JSON.stringify({name: bindingName, seq, args}));
      return promise;
    };
  }