(function () {
  // Theme toggle
  var themeBtn = document.getElementById("theme-toggle");
  if (themeBtn) {
    themeBtn.addEventListener("click", function () {
      var cur = document.documentElement.getAttribute("data-theme");
      var next = cur === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      localStorage.setItem("spnews-theme", next);
    });
  }

  // Report page filters (sport pills + high-importance toggle)
  var pills = document.querySelectorAll("[data-sport-filter]");
  var highToggle = document.getElementById("high-only-toggle");
  var sections = document.querySelectorAll(".sport-section");
  var activeSport = "all";

  function applyReportFilters() {
    var highOnly = !!(highToggle && highToggle.checked);
    sections.forEach(function (sec) {
      var sport = sec.getAttribute("data-sport");
      var sportMatches = activeSport === "all" || activeSport === sport;
      if (!sportMatches) {
        sec.hidden = true;
        return;
      }
      var cards = sec.querySelectorAll(".event-card");
      var visibleCards = 0;
      cards.forEach(function (card) {
        var imp = card.getAttribute("data-importance");
        var show = !highOnly || imp === "high";
        card.hidden = !show;
        if (show) visibleCards += 1;
      });
      sec.hidden = visibleCards === 0;
    });
  }

  pills.forEach(function (btn) {
    btn.addEventListener("click", function () {
      activeSport = btn.getAttribute("data-sport-filter") || "all";
      pills.forEach(function (p) {
        p.classList.toggle("active", p === btn);
      });
      applyReportFilters();
    });
  });

  if (highToggle) {
    highToggle.addEventListener("change", applyReportFilters);
  }

  // Archive search
  var searchInput = document.getElementById("archive-search");
  var archiveGroups = document.querySelectorAll(".archive-month");
  var archiveEmpty = document.getElementById("archive-empty");
  if (searchInput && archiveGroups.length > 0) {
    searchInput.addEventListener("input", function () {
      var q = searchInput.value.trim().toLowerCase();
      var totalVisible = 0;
      archiveGroups.forEach(function (group) {
        var items = group.querySelectorAll(".archive-item");
        var groupVisible = 0;
        items.forEach(function (item) {
          var blob = item.getAttribute("data-search") || "";
          var match = !q || blob.indexOf(q) !== -1;
          item.hidden = !match;
          if (match) {
            groupVisible += 1;
            totalVisible += 1;
          }
        });
        group.hidden = groupVisible === 0;
      });
      if (archiveEmpty) {
        archiveEmpty.hidden = totalVisible > 0;
      }
    });
  }
})();
