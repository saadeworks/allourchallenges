// Filter-as-you-type for long lists (country index, later essays).
// Markup: a [data-filter] block (hidden until this script runs) containing an
// <input>, a [data-filter-status] element and the id of the list area in
// data-filter-target. Each item to filter has data-search="words to match".
// Groups ([data-filter-group]) are hidden when none of their items match.
// Without JavaScript the box stays hidden and the full list still works.
(function () {
  "use strict";

  // Lowercase and strip accents, so "aland" matches "Åland".
  function fold(text) {
    return text.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();
  }

  document.querySelectorAll("[data-filter]").forEach(function (box) {
    var input = box.querySelector("input");
    var status = box.querySelector("[data-filter-status]");
    var target = document.getElementById(box.dataset.filterTarget);
    if (!input || !target) return;

    var items = Array.prototype.map.call(target.querySelectorAll("[data-search]"), function (el) {
      return { el: el, text: fold(el.dataset.search + " " + el.textContent) };
    });
    var groups = target.querySelectorAll("[data-filter-group]");

    function apply() {
      var words = fold(input.value).trim().split(/\s+/).filter(Boolean);
      var shown = 0;
      items.forEach(function (item) {
        var match = words.every(function (w) { return item.text.indexOf(w) !== -1; });
        item.el.hidden = !match;
        if (match) shown++;
      });
      groups.forEach(function (group) {
        group.hidden = !group.querySelector("[data-search]:not([hidden])");
      });
      status.textContent = words.length
        ? (shown === 0 ? box.dataset.textNone : box.dataset.textCount.replace("%d", shown))
        : "";
    }

    input.addEventListener("input", apply);
    box.hidden = false;
    if (input.value) apply(); // e.g. text restored by the back button
  });
})();
