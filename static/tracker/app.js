(() => {
  const isInternalURL = (url) => url.origin === window.location.origin;
  const isNativeURL = (url) => /^\/(account|admin|password-reset|login|logout)(\/|$)/.test(url.pathname);
  let navigation;
  let navigationControls = [];
  let saving = false;
  let displayedURL = window.location.href;
  const deleteDialog = document.getElementById("delete-dialog");
  const deleteContent = deleteDialog?.querySelector("[data-delete-dialog-content]");
  let deleteTrigger;

  function restoreNavigationControls() {
    navigationControls.forEach((control) => { control.disabled = false; });
    navigationControls = [];
  }

  async function fillDeleteDialog(response) {
    if (!response.ok) throw new Error("Request failed");
    if (isNativeURL(new URL(response.url))) {
      window.location.assign(response.url);
      return;
    }
    const page = new DOMParser().parseFromString(await response.text(), "text/html");
    const confirmation = page.querySelector("[data-delete-confirmation]");
    if (!confirmation) throw new Error("Missing confirmation");
    deleteContent.replaceChildren(confirmation);
    const focusTarget = deleteContent.querySelector(".notice.error, .field-error, [data-delete-cancel]");
    if (focusTarget) {
      focusTarget.tabIndex = focusTarget.matches("a") ? 0 : -1;
      focusTarget.focus();
    }
  }

  async function openDeleteDialog(url, trigger) {
    navigation?.abort();
    restoreNavigationControls();
    navigation = new AbortController();
    const signal = navigation.signal;
    deleteTrigger = trigger;
    document.querySelector("#main")?.removeAttribute("aria-busy");
    const loading = document.createElement("p");
    loading.id = "delete-title";
    loading.className = "dialog-loading";
    loading.textContent = "Loading confirmation…";
    deleteContent.replaceChildren(loading);
    deleteDialog.showModal();
    try {
      const response = await fetch(url, {credentials: "same-origin", signal,
        headers: {"X-Requested-With": "XMLHttpRequest"}});
      if (!signal.aborted && deleteDialog.open) await fillDeleteDialog(response);
    } catch {
      if (!signal.aborted) {
        deleteDialog.close();
        showFailure("Could not open the delete confirmation. Please try again.");
      }
    }
  }

  deleteDialog?.addEventListener("cancel", (event) => {
    if (saving) event.preventDefault();
  });
  deleteDialog?.addEventListener("click", (event) => {
    if (event.target === deleteDialog && !saving) deleteDialog.close();
  });
  deleteDialog?.addEventListener("close", () => {
    if (!saving) navigation?.abort();
    if (deleteTrigger?.isConnected) deleteTrigger.focus({preventScroll: true});
  });

  function initializePage() {
    updatePaidByVisibility();
    document.querySelectorAll("details:has(.field-error)").forEach((detail) => { detail.open = true; });
  }

  function showFailure(message, target = document.querySelector("#main")) {
    document.getElementById("request-error")?.remove();
    const notice = document.createElement("div");
    notice.id = "request-error";
    notice.className = "notice error";
    notice.setAttribute("role", "alert");
    notice.tabIndex = -1;
    notice.textContent = message;
    target.prepend(notice);
    notice.focus();
  }

  function updatePaidByVisibility() {
    const kinds = document.getElementById("account-kinds");
    const accountSelect = document.getElementById("id_account");
    const paidByField = document.querySelector("[data-paid-by]");
    if (!kinds || !accountSelect || !paidByField) return;
    const accountKinds = JSON.parse(kinds.textContent);
    paidByField.hidden = accountKinds[accountSelect.value] !== "other";
  }

  async function renderResponse(response, requestedURL, { replace = false, signal } = {}) {
    const currentMain = document.querySelector("#main");
    if (signal?.aborted) return;
    if (!response.ok) throw new Error("Request failed");
    if (isNativeURL(new URL(response.url))) {
      window.location.assign(response.url);
      return;
    }
    const contentType = response.headers.get("content-type") || "";
    if (!contentType.includes("text/html")) {
      throw new Error("Unexpected response");
    }

    const html = await response.text();
    if (signal?.aborted) return;
    const nextDocument = new DOMParser().parseFromString(html, "text/html");
    const nextMain = nextDocument.querySelector("#main");
    if (!nextMain || !currentMain) {
      throw new Error("Missing page content");
    }

    const nextSidebar = nextDocument.querySelector(".sidebar");
    const currentSidebar = document.querySelector(".sidebar");
    if (nextSidebar && currentSidebar) currentSidebar.replaceWith(nextSidebar);
    else if (nextSidebar) document.body.insertBefore(nextSidebar, currentMain);
    else currentSidebar?.remove();

    currentMain.className = nextMain.className;
    currentMain.innerHTML = nextMain.innerHTML;
    currentMain.removeAttribute("aria-busy");
    document.title = nextDocument.title;
    initializePage();

    const finalURL = new URL(response.url);
    if (requestedURL.hash && finalURL.pathname === requestedURL.pathname) {
      finalURL.hash = requestedURL.hash;
    }
    window.history[replace ? "replaceState" : "pushState"]({}, "", finalURL);
    displayedURL = finalURL.href;

    if (finalURL.hash) {
      document.getElementById(decodeURIComponent(finalURL.hash.slice(1)))?.scrollIntoView();
    } else {
      window.scrollTo(0, 0);
    }
    const focusTarget = currentMain.querySelector(".field-error, .notice.error") || currentMain.querySelector("h1");
    if (focusTarget) {
      focusTarget.tabIndex = -1;
      focusTarget.focus({ preventScroll: true });
      if (focusTarget.matches(".field-error, .notice.error")) focusTarget.scrollIntoView({ block: "center" });
    }
  }

  async function visit(url, { replace = false } = {}) {
    if (deleteDialog?.open && !saving) deleteDialog.close();
    navigation?.abort();
    restoreNavigationControls();
    navigation = new AbortController();
    const signal = navigation.signal;
    const requestedURL = new URL(url, window.location.href);
    const requestURL = new URL(requestedURL);
    requestURL.hash = "";
    // Keep the old form from accepting edits while its page is being replaced.
    navigationControls = [...document.querySelectorAll("#main button, #main input:not([type='hidden']), #main select, #main textarea")]
      .filter((control) => !control.disabled);
    navigationControls.forEach((control) => { control.disabled = true; });
    document.querySelector("#main")?.setAttribute("aria-busy", "true");
    try {
      const response = await fetch(requestURL, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
        signal,
      });
      await renderResponse(response, requestedURL, { replace, signal });
    } catch {
      if (!signal.aborted) {
        window.history.replaceState({}, "", displayedURL);
        showFailure("Could not open this page. Please try the link again.");
      }
    } finally {
      if (!signal.aborted) {
        restoreNavigationControls();
        document.querySelector("#main")?.removeAttribute("aria-busy");
      }
    }
  }

  document.addEventListener("click", (event) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = event.target.closest("a[href]");
    if (!link || link.hasAttribute("download") || link.target || link.dataset.native !== undefined) return;

    if (link.matches("[data-delete-cancel]") && deleteDialog?.open && deleteDialog.contains(link)) {
      event.preventDefault();
      if (!saving) deleteDialog.close();
      return;
    }

    const url = new URL(link.href, window.location.href);
    if (!isInternalURL(url)) return;
    if (saving) { event.preventDefault(); return; }
    if (isNativeURL(url) || url.pathname === "/export/") return;
    if (url.pathname === window.location.pathname && url.search === window.location.search && url.hash) return;

    event.preventDefault();
    if (deleteDialog && typeof deleteDialog.showModal === "function" && /^\/(transactions|stock|products)\/\d+\/(delete|void)\/$/.test(url.pathname)) {
      openDeleteDialog(url.href, link);
      return;
    }
    visit(url.href);
  });

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || form.target || form.dataset.native !== undefined || form.enctype === "multipart/form-data") return;

    const method = (form.method || "get").toLowerCase();
    // A submit button named "action" shadows form.action in the browser DOM.
    const url = new URL(form.getAttribute("action") || window.location.href, window.location.href);
    if (saving) { event.preventDefault(); return; }
    if (!isInternalURL(url) || isNativeURL(url)) return;

    event.preventDefault();
    const data = event.submitter ? new FormData(form, event.submitter) : new FormData(form);
    if (method === "get") {
      url.search = "";
      data.forEach((value, key) => url.searchParams.append(key, value));
      visit(url.href);
      return;
    }

    const requestURL = new URL(url);
    requestURL.hash = "";
    navigation?.abort();
    saving = true;
    // Capture FormData first, then prevent edits until this response finishes.
    const controls = [...form.querySelectorAll("button, input:not([type='hidden']), select, textarea")]
      .filter((control) => !control.disabled);
    controls.forEach((control) => { control.disabled = true; });
    form.setAttribute("aria-busy", "true");
    const main = document.querySelector("#main");
    const modalDelete = form.matches("[data-delete-form]") && deleteDialog?.contains(form);
    main?.setAttribute("aria-busy", "true");
    fetch(requestURL, {
      method: form.method.toUpperCase(),
      body: data,
      headers: { "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
    }).then(async (response) => {
      if (modalDelete && response.url === requestURL.href) {
        await fillDeleteDialog(response);
        return;
      }
      if (modalDelete) deleteDialog.close();
      await renderResponse(response, url, { replace: response.url === requestURL.href });
    }).catch(() => {
      showFailure(modalDelete
        ? "We could not confirm this delete. Check the record list before trying again."
        : "We could not confirm this save. Your entries are still in the form. Check the record list before trying again.",
        modalDelete && deleteDialog.open ? deleteContent : document.querySelector("#main"));
    }).finally(() => {
      saving = false;
      controls.forEach((control) => { control.disabled = false; });
      form.removeAttribute("aria-busy");
      document.querySelector("#main")?.removeAttribute("aria-busy");
    });
  });

  document.addEventListener("change", (event) => {
    if (event.target.id === "id_account") updatePaidByVisibility();
  });

  document.addEventListener("invalid", (event) => {
    const detail = event.target.closest("details");
    if (detail) detail.open = true;
  }, true);
  window.addEventListener("popstate", () => {
    if (saving) window.history.pushState({}, "", displayedURL);
    else visit(window.location.href, { replace: true });
  });
  initializePage();
})();
