// ==========================================
// Centralized API Client & Frontend Utilities
// ==========================================

(function () {
  // 1. Centralized API Client Layer (Phase 2 Requirement)
  function getCookie(name) {
    var cookieValue = null;
    if (document.cookie && document.cookie !== "") {
      var cookies = document.cookie.split(";");
      for (var i = 0; i < cookies.length; i++) {
        var cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === name + "=") {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }

  window.ApiClient = {
    csrfToken: function () {
      return getCookie("csrftoken") || "";
    },

    request: function (url, options) {
      options = options || {};
      options.headers = options.headers || {};
      options.headers["Accept"] = "application/json";

      if (options.method && options.method.toUpperCase() !== "GET") {
        options.headers["X-CSRFToken"] = this.csrfToken();
        if (options.json) {
          options.headers["Content-Type"] = "application/json";
          options.body = JSON.stringify(options.json);
        }
      }

      return fetch(url, options).then(function (response) {
        return response.json().then(function (data) {
          if (!response.ok) {
            var error = new Error(data.message || "Request failed with status " + response.status);
            error.status = response.status;
            error.data = data;
            throw error;
          }
          return data;
        });
      });
    },

    get: function (url) {
      return this.request(url, { method: "GET" });
    },

    post: function (url, payload) {
      return this.request(url, { method: "POST", json: payload });
    }
  };

  // 2. Health check indicator on landing page
  var el = document.getElementById("system-status");
  if (el) {
    var text = document.getElementById("system-status-text");
    var dot = el.querySelector(".dot");
    window.ApiClient.get(el.dataset.healthUrl || "/api/health/")
      .then(function (data) {
        var ok = data.status === "ok";
        text.textContent = ok
          ? "System online — backend and database are reachable."
          : "System degraded — database is not reachable.";
        dot.className = "dot " + (ok ? "dot-ok" : "dot-bad");
      })
      .catch(function () {
        text.textContent = "System offline — cannot reach the backend.";
        dot.className = "dot dot-bad";
      });
  }

  // 3. Officer update form: toggle evidence upload when resolving
  var statusSelect = document.querySelector("select[name=status]");
  var evidenceField = document.querySelector("[data-field=evidence]");
  if (statusSelect && evidenceField) {
    var syncEvidence = function () {
      evidenceField.hidden = statusSelect.value !== "resolved";
    };
    statusSelect.addEventListener("change", syncEvidence);
    syncEvidence();
  }

  // 4. Duplicate submission prevention
  document.querySelectorAll("form[data-once]").forEach(function (form) {
    form.addEventListener("submit", function () {
      var btn = form.querySelector("button[type=submit]");
      if (btn) {
        setTimeout(function () { btn.disabled = true; }, 0);
      }
    });
  });

  // 5. Persistent Help & Support Dialog (REQ-UI)
  var helpDialog = document.getElementById("help-modal");
  var openHelpBtn = document.getElementById("help-modal-open-btn");
  var closeHelpBtn = document.getElementById("help-modal-close-btn");
  var okHelpBtn = document.getElementById("help-modal-ok-btn");

  if (helpDialog && openHelpBtn) {
    openHelpBtn.addEventListener("click", function () {
      if (typeof helpDialog.showModal === "function") {
        helpDialog.showModal();
      } else {
        helpDialog.setAttribute("open", "true");
      }
    });
    var closeHandler = function () {
      if (typeof helpDialog.close === "function") {
        helpDialog.close();
      } else {
        helpDialog.removeAttribute("open");
      }
    };
    if (closeHelpBtn) closeHelpBtn.addEventListener("click", closeHandler);
    if (okHelpBtn) okHelpBtn.addEventListener("click", closeHandler);
  }

  // 6. Multilingual Language Selector (English / Hindi toggle, REQ-UI)
  var langBtn = document.getElementById("lang-toggle-btn");
  var langLabel = document.getElementById("current-lang-label");
  var translations = {
    hi: {
      "Dashboard": "डैशबोर्ड",
      "Submit complaint": "शिकायत दर्ज करें",
      "My grievances": "मेरी शिकायतें",
      "Assigned queue": "सौंपी गई सूची",
      "All complaints": "सभी शिकायतें",
      "Live map": "लाइव मानचित्र",
      "Analytics": "एनालिटिक्स",
      "Officers": "अधिकारी",
      "Notifications": "सूचनाएं",
      "Profile": "प्रोफ़ाइल",
      "Log out": "लॉग आउट",
      "Log in": "लॉग इन",
      "OTP Login": "ओटीपी लॉगिन",
      "Register": "पंजीकरण",
      "Help": "सहायता"
    }
  };

  var currentLang = localStorage.getItem("portal_lang") || "en";
  function applyLanguage(lang) {
    if (langLabel) langLabel.textContent = lang.toUpperCase();
    if (lang === "hi") {
      document.querySelectorAll(".main-nav a, .main-nav button").forEach(function (elem) {
        var txt = elem.textContent.trim();
        if (translations.hi[txt]) {
          elem.dataset.origText = txt;
          elem.textContent = translations.hi[txt];
        }
      });
    } else {
      document.querySelectorAll(".main-nav a, .main-nav button").forEach(function (elem) {
        if (elem.dataset.origText) {
          elem.textContent = elem.dataset.origText;
        }
      });
    }
  }

  if (langBtn) {
    langBtn.addEventListener("click", function () {
      currentLang = currentLang === "en" ? "hi" : "en";
      localStorage.setItem("portal_lang", currentLang);
      applyLanguage(currentLang);
    });
    if (currentLang === "hi") {
      applyLanguage("hi");
    }
  }
})();
