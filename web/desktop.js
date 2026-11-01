/* Transport for the packaged desktop app. The browser demo keeps its HTTP API. */
'use strict';
(() => {
  const isDesktop = window.location.protocol === 'file:' || Boolean(window.qt?.webChannelTransport);
  const pending = new Map();
  let bridge = null;
  let sequence = 0;

  const ready = isDesktop ? new Promise((resolve, reject) => {
    let finished = false;
    let pollTimer;
    const startupTimer = setTimeout(() => fail(new Error('The desktop connection did not start. Close and reopen Survey Design Lab.')), 10000);

    function fail(error) {
      if (finished) return;
      finished = true;
      clearTimeout(startupTimer);
      clearTimeout(pollTimer);
      reject(error);
    }

    function connect() {
      if (finished) return;
      if (!window.qt?.webChannelTransport) {
        pollTimer = setTimeout(connect, 50);
        return;
      }
      const script = document.createElement('script');
      script.src = 'qrc:///qtwebchannel/qwebchannel.js';
      script.onerror = () => fail(new Error('The desktop connection could not be loaded. Close and reopen Survey Design Lab.'));
      script.onload = () => {
        if (finished) return;
        try {
          if (typeof window.QWebChannel !== 'function') throw new Error('The desktop connection is unavailable.');
          new window.QWebChannel(window.qt.webChannelTransport, channel => {
            if (finished) return;
            try {
              const native = channel.objects.desktopBridge;
              if (!native || typeof native.request !== 'function' || typeof native.response?.connect !== 'function') {
                throw new Error('The desktop application did not provide its data connection.');
              }
              native.response.connect((requestId, envelopeJson) => {
                const request = pending.get(requestId);
                if (!request) return;
                pending.delete(requestId);
                clearTimeout(request.timer);
                try {
                  const envelope = JSON.parse(envelopeJson);
                  if (!envelope || typeof envelope.ok !== 'boolean') throw new Error('Invalid response from the desktop application.');
                  if (envelope.ok) request.resolve(envelope.data);
                  else request.reject(new Error(String(envelope.error || 'The desktop request failed.')));
                } catch (error) {
                  request.reject(error);
                }
              });
              bridge = native;
              finished = true;
              clearTimeout(startupTimer);
              clearTimeout(pollTimer);
              resolve(native);
            } catch (error) {
              fail(error);
            }
          });
        } catch (error) {
          fail(error);
        }
      };
      document.head.appendChild(script);
    }
    connect();
  }) : Promise.resolve(null);

  // Initialization may fail before app.js has attached its request handler.
  ready.catch(() => {});

  async function request(path, body) {
    await ready;
    if (!bridge) throw new Error('The desktop connection is unavailable in browser mode.');
    const payloadJson = body == null ? 'null' : JSON.stringify(body);
    const requestId = Date.now().toString(36) + '-' + (++sequence);
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        pending.delete(requestId);
        reject(new Error('The desktop request took longer than 120 seconds. Try again.'));
      }, 120000);
      pending.set(requestId, {resolve, reject, timer});
      try {
        bridge.request(requestId, path, payloadJson);
      } catch (error) {
        pending.delete(requestId);
        clearTimeout(timer);
        reject(error);
      }
    });
  }

  window.SurveyDesktop = {
    isDesktop,
    ready,
    request,
    saveJson: (content, filename) => request('/desktop/save', {content, filename})
  };
})();
