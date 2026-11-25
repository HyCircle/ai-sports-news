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

  // Collapse TOC details by default on narrow viewports so mobile isn't pushed down
  var tocPanel = document.getElementById("toc-panel");
  if (tocPanel && window.matchMedia("(max-width: 1120px)").matches) {
    tocPanel.removeAttribute("open");
  }

  // Report page filters (sport pills + high-only toggle + instant keyword search)
  var pills = document.querySelectorAll("[data-sport-filter]");
  var highToggle = document.getElementById("high-only-toggle");
  var reportSearch = document.getElementById("report-search");
  var sections = document.querySelectorAll(".sport-section");
  var tocGroups = document.querySelectorAll(".toc-group");
  var visibleCountEl = document.getElementById("visible-count");
  var filterEmptyEl = document.getElementById("filter-empty");
  var totalCards = document.querySelectorAll(".event-card").length;
  var activeSport = "all";

  function applyReportFilters() {
    var highOnly = !!(highToggle && highToggle.checked);
    var q = reportSearch ? reportSearch.value.trim().toLowerCase() : "";
    var visibleTotal = 0;

    sections.forEach(function (sec) {
      var sport = sec.getAttribute("data-sport");
      var sportMatches = activeSport === "all" || activeSport === sport;
      var cards = sec.querySelectorAll(".event-card");
      var visibleCards = 0;

      cards.forEach(function (card) {
        var imp = card.getAttribute("data-importance");
        var blob = card.getAttribute("data-search") || "";
        var show = sportMatches && (!highOnly || imp === "high") && (!q || blob.indexOf(q) !== -1);
        card.hidden = !show;
        if (show) {
          visibleCards += 1;
          visibleTotal += 1;
        }
      });

      sec.hidden = visibleCards === 0;
      var countEl = sec.querySelector(".sport-count");
      if (countEl) {
        var orig = countEl.getAttribute("data-total") || cards.length;
        countEl.textContent = visibleCards === Number(orig) ? orig + " 条" : visibleCards + " / " + orig + " 条";
      }
    });

    tocGroups.forEach(function (group) {
      var sport = group.getAttribute("data-sport");
      var sportMatches = activeSport === "all" || activeSport === sport;
      var items = group.querySelectorAll(".toc-item");
      var visibleItems = 0;

      items.forEach(function (item) {
        var imp = item.getAttribute("data-importance");
        var blob = item.getAttribute("data-search") || "";
        var show = sportMatches && (!highOnly || imp === "high") && (!q || blob.indexOf(q) !== -1);
        item.hidden = !show;
        if (show) visibleItems += 1;
      });

      group.hidden = visibleItems === 0;
      var gCount = group.querySelector(".toc-sport-count");
      if (gCount) gCount.textContent = String(visibleItems);
    });

    if (visibleCountEl) {
      visibleCountEl.textContent = visibleTotal + "/" + totalCards;
    }
    if (filterEmptyEl) {
      filterEmptyEl.hidden = visibleTotal > 0;
    }
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
  if (reportSearch) {
    reportSearch.addEventListener("input", applyReportFilters);
  }

  // Click-to-jump helper: if jumping to a filtered-out card, reset filters so it becomes visible
  document.querySelectorAll("[data-jump]").forEach(function (link) {
    link.addEventListener("click", function () {
      var targetId = link.getAttribute("data-jump");
      var targetEl = targetId ? document.getElementById(targetId) : null;
      if (targetEl && targetEl.hidden) {
        activeSport = "all";
        pills.forEach(function (p) {
          p.classList.toggle("active", p.getAttribute("data-sport-filter") === "all");
        });
        if (highToggle) highToggle.checked = false;
        if (reportSearch) reportSearch.value = "";
        applyReportFilters();
      }
      if (targetEl) {
        document.querySelectorAll(".event-card.is-target").forEach(function (el) {
          el.classList.remove("is-target");
        });
        targetEl.classList.add("is-target");
      }
    });
  });

  // Scroll-spy for left TOC on desktop
  var tocNav = document.getElementById("toc-nav");
  var eventCards = document.querySelectorAll(".event-card[id]");
  if (tocNav && eventCards.length > 0 && "IntersectionObserver" in window) {
    var tocMap = {};
    tocNav.querySelectorAll(".toc-link[data-target]").forEach(function (a) {
      tocMap[a.getAttribute("data-target")] = a;
    });
    var currentActive = null;

    var observer = new IntersectionObserver(
      function (entries) {
        var best = null;
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            if (!best || entry.boundingClientRect.top < best.boundingClientRect.top) {
              best = entry;
            }
          }
        });
        if (!best) return;
        var nextLink = tocMap[best.target.id];
        if (nextLink && nextLink !== currentActive) {
          if (currentActive) currentActive.classList.remove("is-active");
          nextLink.classList.add("is-active");
          currentActive = nextLink;
        }
      },
      { rootMargin: "-10% 0px -75% 0px", threshold: 0 }
    );

    eventCards.forEach(function (card) {
      observer.observe(card);
    });
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
