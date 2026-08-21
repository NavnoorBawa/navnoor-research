/* Navnoor Research — article search, checked headlines, ticker discovery.
 *
 * Everything here runs on data already in the page's origin. What you type is
 * never written to the URL, to storage, or to a network request: it lives in a
 * local variable and nowhere else.
 */
(function () {
  "use strict";

  var PAGE_SIZE = 40;
  var DEBOUNCE_MS = 90;

  var state = {
    tab: "articles",
    query: "",
    topic: "",
    access: "",
    sort: "relevance",
    limit: PAGE_SIZE,
    entity: null
  };

  var data = { articles: [], news: [], entities: {}, topics: {}, sources: {}, checkedAt: null };
  var el = {};

  /* ---------- utilities ---------- */

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function tokenize(text) {
    return String(text || "").toLowerCase().split(/[^a-z0-9&.+-]+/).filter(Boolean);
  }

  function formatDate(iso) {
    var parts = String(iso || "").slice(0, 10).split("-");
    if (parts.length !== 3) { return ""; }
    var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    var month = months[parseInt(parts[1], 10) - 1] || "";
    return parseInt(parts[2], 10) + " " + month + " " + parts[0];
  }

  function relativeTime(iso) {
    var then = Date.parse(iso);
    if (isNaN(then)) { return formatDate(iso); }
    var mins = Math.round((Date.now() - then) / 60000);
    if (mins < 1) { return "just checked"; }
    if (mins < 60) { return mins + "m ago"; }
    if (mins < 1440) { return Math.round(mins / 60) + "h ago"; }
    var days = Math.round(mins / 1440);
    if (days <= 14) { return days + "d ago"; }
    return formatDate(iso);
  }

  function debounce(fn, wait) {
    var timer = null;
    return function () {
      if (timer) { clearTimeout(timer); }
      timer = setTimeout(fn, wait);
    };
  }

  /* ---------- indexing ---------- */

  // Each record gets one lowercase haystack, built once, so keystroke-time work
  // is a substring scan and nothing more.
  function prepare(record) {
    var names = (record.entities || []).map(function (id) {
      return (data.entities[id] || {}).label || id;
    });
    var topicLabel = data.topics[record.topic] || record.topic || "";
    var sourceLabel = data.sources[record.source || record.source_id] ||
                      record.source || record.source_id || "";
    record._names = names;
    record._topicLabel = topicLabel;
    record._sourceLabel = sourceLabel;
    record._title = String(record.title || "").toLowerCase();
    record._hay = [record.title, record.summary, names.join(" "), topicLabel, sourceLabel]
      .join(" ").toLowerCase();
    return record;
  }

  function score(record, tokens) {
    var total = 0;
    for (var i = 0; i < tokens.length; i += 1) {
      var token = tokens[i];
      if (record._hay.indexOf(token) === -1) { return 0; }

      var inTitle = record._title.indexOf(token);
      if (inTitle !== -1) {
        total += 12;
        // A hit at a word boundary is a real term, not an accident inside another word.
        if (inTitle === 0 || /[^a-z0-9]/.test(record._title.charAt(inTitle - 1))) { total += 8; }
      }
      for (var n = 0; n < record._names.length; n += 1) {
        var name = record._names[n].toLowerCase();
        if (name === token) { total += 30; break; }
        if (name.indexOf(token) !== -1) { total += 10; break; }
      }
      if (record._topicLabel.toLowerCase().indexOf(token) !== -1) { total += 6; }
      if (record.summary && String(record.summary).toLowerCase().indexOf(token) !== -1) {
        total += 3;
      }
      if (record._sourceLabel.toLowerCase().indexOf(token) !== -1) { total += 2; }
    }
    return total;
  }

  /* ---------- entity resolution ---------- */

  // Does the whole query name one entity? That is what turns a search box into
  // a discovery view.
  function resolveEntity(query) {
    var needle = query.trim().toLowerCase();
    if (needle.length < 2) { return null; }
    var ids = Object.keys(data.entities);
    var partial = null;
    for (var i = 0; i < ids.length; i += 1) {
      var entity = data.entities[ids[i]];
      var label = entity.label.toLowerCase();
      if (label === needle) { return ids[i]; }
      var aliases = entity.aliases || [];
      for (var a = 0; a < aliases.length; a += 1) {
        if (aliases[a].toLowerCase() === needle) { return ids[i]; }
      }
      if (partial === null && needle.length >= 3 && label.indexOf(needle) === 0) {
        partial = ids[i];
      }
    }
    return partial;
  }

  /* ---------- filtering ---------- */

  function select(records, isNews) {
    var tokens = tokenize(state.query);
    var out = [];

    for (var i = 0; i < records.length; i += 1) {
      var record = records[i];
      if (state.topic && record.topic !== state.topic) { continue; }
      if (!isNews && state.access && record.access !== state.access) { continue; }
      if (state.entity && (record.entities || []).indexOf(state.entity) === -1) { continue; }

      var relevance = 0;
      if (tokens.length) {
        relevance = score(record, tokens);
        if (!relevance) { continue; }
      }
      record._score = relevance;
      out.push(record);
    }

    var sort = state.sort;
    if (sort === "relevance" && !tokens.length) { sort = "newest"; }
    out.sort(function (a, b) {
      if (sort === "relevance" && b._score !== a._score) { return b._score - a._score; }
      if (sort === "oldest") { return a.published < b.published ? -1 : 1; }
      return a.published > b.published ? -1 : 1;
    });
    return out;
  }

  /* ---------- rendering ---------- */

  function highlight(text, tokens) {
    var safe = esc(text);
    if (!tokens.length) { return safe; }
    var pattern = tokens
      .filter(function (t) { return t.length > 1; })
      .map(function (t) { return t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); })
      .join("|");
    if (!pattern) { return safe; }
    return safe.replace(new RegExp("(" + pattern + ")", "gi"), '<mark class="mark">$1</mark>');
  }

  function entityTags(record, limit) {
    return (record.entities || []).slice(0, limit).map(function (id) {
      var label = (data.entities[id] || {}).label || id;
      return '<button type="button" class="tag" data-entity="' + esc(id) + '">' +
             esc(label) + "</button>";
    });
  }

  function articleRow(record, tokens) {
    var badge = record.access === "free" ? "free"
              : record.access === "paid" ? "paid" : "unknown";
    var badgeText = record.access === "unknown" ? "—" : record.access;

    var meta = ['<time datetime="' + esc(record.published) + '">' +
                esc(formatDate(record.published)) + "</time>"];
    if (record.reading_minutes) {
      meta.push('<span class="dot">·</span><span>' + record.reading_minutes + " min read</span>");
    }
    meta.push('<span class="dot">·</span><button type="button" class="tag" data-topic="' +
              esc(record.topic) + '">' + esc(record._topicLabel) + "</button>");
    meta.push('<span class="dot">·</span><span>' + esc(record._sourceLabel) + "</span>");

    var tags = entityTags(record, 4);
    if (tags.length) { meta.push('<span class="dot">·</span>' + tags.join(", ")); }

    return '<li class="row">' +
      '<div class="row__head">' +
        '<h3 class="row__title"><a href="' + esc(record.url) +
          '" target="_blank" rel="noopener noreferrer">' +
          highlight(record.title, tokens) + "</a></h3>" +
        '<span class="badge badge--' + badge + '">' + esc(badgeText) + "</span>" +
      "</div>" +
      (record.summary ? '<p class="row__summary">' +
        highlight(record.summary, tokens) + "</p>" : "") +
      '<div class="row__meta">' + meta.join("") + "</div>" +
    "</li>";
  }

  function newsRow(record, tokens) {
    var meta = ['<time datetime="' + esc(record.published) + '">' +
                esc(relativeTime(record.published)) + "</time>",
                '<span class="dot">·</span><span>' + esc(record.attribution) + "</span>",
                '<span class="dot">·</span><button type="button" class="tag" data-topic="' +
                esc(record.topic) + '">' + esc(record._topicLabel) + "</button>"];
    var tags = entityTags(record, 4);
    if (tags.length) { meta.push('<span class="dot">·</span>' + tags.join(", ")); }

    return '<li class="row">' +
      '<div class="row__head">' +
        '<h3 class="row__title"><a href="' + esc(record.url) +
          '" target="_blank" rel="noopener noreferrer">' +
          highlight(record.title, tokens) + "</a></h3>" +
      "</div>" +
      '<div class="row__meta">' + meta.join("") + "</div>" +
    "</li>";
  }

  function renderDiscovery() {
    var id = state.entity || (state.query ? resolveEntity(state.query) : null);
    if (!id || !data.entities[id]) {
      el.discovery.hidden = true;
      return;
    }
    var entity = data.entities[id];
    var articles = data.articles.filter(function (r) {
      return (r.entities || []).indexOf(id) !== -1;
    }).length;
    var headlines = data.news.filter(function (r) {
      return (r.entities || []).indexOf(id) !== -1;
    }).length;

    el.discovery.hidden = false;
    el.discovery.innerHTML =
      '<div class="discovery__label">' + esc(entity.kind) + "</div>" +
      '<div class="discovery__name">' + esc(entity.label) + "</div>" +
      '<div class="discovery__stats">' +
        '<button type="button" class="chip" data-go="articles" data-entity="' + esc(id) + '">' +
          "<strong>" + articles + "</strong> article" + (articles === 1 ? "" : "s") + "</button>" +
        '<button type="button" class="chip" data-go="news" data-entity="' + esc(id) + '">' +
          "<strong>" + headlines + "</strong> headline" +
          (headlines === 1 ? "" : "s") + "</button>" +
      "</div>";
  }

  function render() {
    var isNews = state.tab === "news";
    var records = select(isNews ? data.news : data.articles, isNews);
    var tokens = tokenize(state.query);
    var shown = records.slice(0, state.limit);

    renderDiscovery();

    el.count.textContent = records.length.toLocaleString() + " " +
      (isNews ? "headline" : "article") + (records.length === 1 ? "" : "s");

    el.accessFilter.hidden = isNews;

    if (!records.length) {
      el.results.innerHTML = "";
      el.empty.hidden = false;
      el.empty.innerHTML = '<p class="empty__title">Nothing matches that</p>' +
        "<p>Try a company, ticker, fund, regulator or topic — " +
        "or clear the filters.</p>";
      el.more.hidden = true;
      return;
    }

    el.empty.hidden = true;
    var rows = new Array(shown.length);
    for (var i = 0; i < shown.length; i += 1) {
      rows[i] = isNews ? newsRow(shown[i], tokens) : articleRow(shown[i], tokens);
    }
    el.results.innerHTML = rows.join("");

    var remaining = records.length - shown.length;
    el.more.hidden = remaining <= 0;
    if (remaining > 0) {
      el.more.textContent = "Show " + Math.min(remaining, PAGE_SIZE) +
        " more (" + remaining.toLocaleString() + " remaining)";
    }
  }

  /* ---------- controls ---------- */

  function reset() { state.limit = PAGE_SIZE; }

  function setTab(tab) {
    state.tab = tab;
    reset();
    var buttons = el.tabs.querySelectorAll(".tab");
    for (var i = 0; i < buttons.length; i += 1) {
      buttons[i].setAttribute("aria-selected", String(buttons[i].dataset.tab === tab));
    }
    el.input.placeholder = tab === "news"
      ? "Search checked headlines by company, ticker or topic…"
      : "Search " + data.articles.length + " articles by keyword, company, ticker or topic…";
    render();
  }

  function fillSelect(node, entries, allLabel) {
    var html = ['<option value="">' + esc(allLabel) + "</option>"];
    entries.forEach(function (entry) {
      html.push('<option value="' + esc(entry[0]) + '">' + esc(entry[1]) + "</option>");
    });
    node.innerHTML = html.join("");
  }

  function bind() {
    el.input.addEventListener("input", debounce(function () {
      state.query = el.input.value;
      // Typing a fresh query drops any pinned entity so the box stays in charge.
      state.entity = null;
      reset();
      el.clear.hidden = !state.query;
      el.hint.hidden = !!state.query;
      render();
    }, DEBOUNCE_MS));

    el.clear.addEventListener("click", function () {
      el.input.value = "";
      state.query = "";
      state.entity = null;
      reset();
      el.clear.hidden = true;
      el.hint.hidden = false;
      el.input.focus();
      render();
    });

    el.topicFilter.addEventListener("change", function () {
      state.topic = el.topicFilter.value; reset(); render();
    });
    el.accessFilter.addEventListener("change", function () {
      state.access = el.accessFilter.value; reset(); render();
    });
    el.sortFilter.addEventListener("change", function () {
      state.sort = el.sortFilter.value; reset(); render();
    });

    el.tabs.addEventListener("click", function (event) {
      var button = event.target.closest(".tab");
      if (button) { setTab(button.dataset.tab); }
    });

    el.more.addEventListener("click", function () {
      state.limit += PAGE_SIZE;
      render();
    });

    document.addEventListener("click", function (event) {
      var target = event.target.closest("[data-entity],[data-topic]");
      if (!target) { return; }
      if (target.dataset.go) { state.tab = target.dataset.go; }
      if (target.dataset.entity) {
        state.entity = target.dataset.entity;
        el.input.value = "";
        state.query = "";
        el.clear.hidden = true;
        el.hint.hidden = false;
      }
      if (target.dataset.topic) {
        state.topic = target.dataset.topic;
        el.topicFilter.value = state.topic;
      }
      reset();
      setTab(state.tab);
      window.scrollTo({ top: 0, behavior: "smooth" });
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "/" && document.activeElement !== el.input) {
        event.preventDefault();
        el.input.focus();
        el.input.select();
      } else if (event.key === "Escape" && document.activeElement === el.input) {
        el.clear.click();
      }
    });
  }

  /* ---------- boot ---------- */

  function fail(message) {
    el.empty.hidden = false;
    el.empty.innerHTML = '<p class="empty__title">This release could not load</p><p>' +
      esc(message) + "</p>";
  }

  function boot() {
    ["input", "clear", "hint", "tabs", "topicFilter", "accessFilter", "sortFilter",
     "results", "empty", "more", "count", "discovery"].forEach(function (key) {
      el[key] = document.getElementById(key);
    });

    // Payload names carry content digests, so the shell hands them to us on a
    // data element rather than an inline script the CSP would have to allow.
    var manifest = document.getElementById("payloads");
    var urls = {
      articles: manifest.getAttribute("data-articles"),
      news: manifest.getAttribute("data-news"),
      taxonomy: manifest.getAttribute("data-taxonomy")
    };

    Promise.all([
      fetch(urls.articles).then(function (r) { return r.json(); }),
      fetch(urls.news).then(function (r) { return r.json(); }),
      fetch(urls.taxonomy).then(function (r) { return r.json(); })
    ]).then(function (payloads) {
      data.entities = payloads[2].entities || {};
      data.topics = payloads[2].topics || {};
      data.sources = payloads[2].sources || {};
      data.articles = (payloads[0].articles || []).map(prepare);
      data.news = (payloads[1].items || []).map(prepare);
      data.checkedAt = payloads[1].checked_at || null;

      var topicEntries = Object.keys(data.topics).map(function (id) {
        return [id, data.topics[id]];
      }).sort(function (a, b) { return a[1] < b[1] ? -1 : 1; });

      fillSelect(el.topicFilter, topicEntries, "All topics");
      fillSelect(el.accessFilter, [["free", "Free"], ["paid", "Paid"]], "Free and paid");
      fillSelect(el.sortFilter, [["relevance", "Best match"], ["newest", "Newest"],
                                 ["oldest", "Oldest"]], "Best match");
      el.sortFilter.value = "relevance";

      var checked = document.getElementById("checked-at");
      if (checked && data.checkedAt) {
        checked.textContent = "News checked " + relativeTime(data.checkedAt);
      }

      bind();
      setTab("articles");
      el.input.focus();
    }).catch(function (error) {
      fail(String(error && error.message ? error.message : error));
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
