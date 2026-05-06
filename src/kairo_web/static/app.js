// Minimal page-level shortcuts. Row-aware shortcuts (j/k/c/t/s/J/K/d) come in
// a later milestone — they need a row-selection model.
//
//   /  → focus the capture bar
//   ?  → toggle a tiny shortcut hint (TODO)

(function () {
  function isTypingTarget(el) {
    if (!el) return false;
    var tag = el.tagName;
    return (
      tag === "INPUT" ||
      tag === "TEXTAREA" ||
      tag === "SELECT" ||
      el.isContentEditable
    );
  }

  document.addEventListener("keydown", function (e) {
    // Ignore if user is typing somewhere.
    if (isTypingTarget(e.target)) return;
    // Ignore if any modifier is held.
    if (e.metaKey || e.ctrlKey || e.altKey) return;

    if (e.key === "/") {
      var input = document.getElementById("capture-input");
      if (input) {
        e.preventDefault();
        input.focus();
        input.select();
      }
    }
  });
})();
