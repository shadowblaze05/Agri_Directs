(() => {
    const overlay = document.getElementById("global-loading");
    const message = document.getElementById("global-loading-message");
    const networkStatus = document.getElementById("network-status");
    if (!overlay || !message || !networkStatus) return;

    const slowDelay = 350;
    const longDelay = 8000;
    let activeOperations = 0;
    let showTimer;
    let longTimer;

    function showLoading(text) {
        message.textContent = navigator.onLine
            ? text
            : "You are offline. Waiting for your connection...";
        overlay.hidden = false;
        clearTimeout(longTimer);
        longTimer = setTimeout(() => {
            if (activeOperations > 0) {
                message.textContent = navigator.onLine
                    ? "This is taking longer than usual..."
                    : "You are offline. Waiting for your connection...";
            }
        }, longDelay);
    }

    function beginOperation(text = "Loading...") {
        activeOperations += 1;
        if (activeOperations === 1) {
            clearTimeout(showTimer);
            showTimer = setTimeout(() => showLoading(text), slowDelay);
        }
        let finished = false;
        return () => {
            if (finished) return;
            finished = true;
            activeOperations = Math.max(0, activeOperations - 1);
            if (activeOperations === 0) {
                clearTimeout(showTimer);
                clearTimeout(longTimer);
                overlay.hidden = true;
            }
        };
    }

    function isSameOrigin(value) {
        try {
            return new URL(value, window.location.href).origin === window.location.origin;
        } catch {
            return false;
        }
    }

    document.addEventListener("click", (event) => {
        if (
            event.defaultPrevented ||
            event.button !== 0 ||
            event.metaKey ||
            event.ctrlKey ||
            event.shiftKey ||
            event.altKey
        ) return;

        const link = event.target.closest("a[href]");
        if (
            !link ||
            link.target && link.target !== "_self" ||
            link.hasAttribute("download") ||
            !isSameOrigin(link.href)
        ) return;

        const destination = new URL(link.href, window.location.href);
        if (
            destination.pathname === window.location.pathname &&
            destination.search === window.location.search &&
            destination.hash
        ) return;
        beginOperation("Loading page...");
    });

    document.addEventListener("submit", (event) => {
        if (event.defaultPrevented) return;
        const form = event.target;
        if (
            !(form instanceof HTMLFormElement) ||
            form.target && form.target !== "_self" ||
            !isSameOrigin(form.action)
        ) return;
        beginOperation("Submitting...");
    });

    if (window.fetch) {
        const originalFetch = window.fetch.bind(window);
        window.fetch = (...args) => {
            const input = args[0];
            const url = input instanceof Request ? input.url : input;
            if (!isSameOrigin(url)) return originalFetch(...args);
            const finish = beginOperation("Loading...");
            return originalFetch(...args).finally(finish);
        };
    }

    const xhrOrigins = new WeakMap();
    const originalXhrOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function (method, url, ...args) {
        xhrOrigins.set(this, isSameOrigin(url));
        return originalXhrOpen.call(this, method, url, ...args);
    };

    const originalXhrSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.send = function (...args) {
        if (xhrOrigins.get(this) === false) {
            return originalXhrSend.apply(this, args);
        }
        const finish = beginOperation("Loading...");
        this.addEventListener("loadend", finish, { once: true });
        try {
            return originalXhrSend.apply(this, args);
        } catch (error) {
            finish();
            throw error;
        }
    };

    function updateNetworkStatus() {
        networkStatus.hidden = navigator.onLine;
        if (!navigator.onLine && activeOperations > 0) {
            message.textContent = "You are offline. Waiting for your connection...";
            overlay.hidden = false;
        }
    }

    window.addEventListener("online", updateNetworkStatus);
    window.addEventListener("offline", updateNetworkStatus);
    window.addEventListener("pageshow", () => {
        activeOperations = 0;
        clearTimeout(showTimer);
        clearTimeout(longTimer);
        overlay.hidden = true;
        updateNetworkStatus();
    });
    updateNetworkStatus();
})();
