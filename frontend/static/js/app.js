// Frontend <-> backend wiring check on the landing page (calls /api/health/).
(function () {
  var el = document.getElementById("system-status");
  if (el) {
    var text = document.getElementById("system-status-text");
    var dot = el.querySelector(".dot");
    fetch(el.dataset.healthUrl, { headers: { Accept: "application/json" } })
      .then(function (r) { return r.json(); })
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

  // Officer update form: only offer the evidence upload when resolving.
  var statusSelect = document.querySelector("select[name=status]");
  var evidenceField = document.querySelector("[data-field=evidence]");
  if (statusSelect && evidenceField) {
    var sync = function () { evidenceField.hidden = statusSelect.value !== "resolved"; };
    statusSelect.addEventListener("change", sync);
    sync();
  }

  // Basic client-side nicety: disable a submit button after the first click
  // to avoid duplicate submissions (server-side validation stays authoritative).
  document.querySelectorAll("form[data-once]").forEach(function (form) {
    form.addEventListener("submit", function () {
      var btn = form.querySelector("button[type=submit]");
      if (btn) { setTimeout(function () { btn.disabled = true; }, 0); }
    });
  });
})();
