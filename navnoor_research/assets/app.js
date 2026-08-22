/* Navnoor Research — all reader queries remain in this page's memory. */
(function () {
  "use strict";

  var PAGE_SIZE = 40;
  var SEARCH_GROUP_SIZE = 8;
  var GDELT_ORIGIN = "https://www.gdeltproject.org/";
  var DATA_CAPS = {
    research: 1000000,
    companies: 1800000,
    news: 750000,
    taxonomy: 300000
  };
  var FORBIDDEN_KEYS = {
    article_body: true, body: true, body_html: true, body_text: true, brief: true,
    holdings: true, member_preview: true, parser_observations: true, pnl: true,
    position: true, reading_minutes: true, recommendation: true, return: true,
    wordcount: true
  };
  var PROHIBITED_HEADLINE = /(?:\blive(?:\s+(?:blog|coverage|updates?))?\b|\bprice\s+target\b|\btarget\s+price\b|\b(?:raise|raises|raised|cut|cuts|lower|lowers|lowered|boost|boosts|boosted|slash|slashes|slashed)\b.{0,80}\b(?:price\s+)?target\b|\b(?:strong\s+)?(?:buy|sell|hold)\s+(?:rating|recommendation)\b|\b(?:is|remains?|rates?)\s+(?:an?\s+)?(?:strong\s+)?(?:buy|sell|hold)\b|\b(?:upgrade|upgrades|upgraded|downgrade|downgrades|downgraded)\b|\b(?:upgrade|downgrade|upgraded|downgraded)\b.{0,80}\bto\s+(?:(?:strong\s+)?(?:buy|sell|hold)|(?:out|under)perform|neutral|overweight|underweight)\b|\bstocks?\s+to\s+(?:buy|sell)\b|\b(?:stock|stocks|investment|investments)\s+picks?\b|\b(?:should|could)\s+(?:you\s+)?(?:buy|sell)\b|\brecommend(?:s|ed|ation|ations)\b)/i;

  var state = {
    view: "search",
    query: "",
    topic: "",
    access: "",
    sort: "newest",
    limit: PAGE_SIZE,
    company: null
  };
  var data = {
    ready: false,
    research: [],
    companies: [],
    news: [],
    entities: {},
    entityLookup: {},
    topics: {},
    sources: {},
    newsStates: {}
  };
  var el = {};
  var bound = false;
  var loading = false;

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function discoveryAttribution(sourceId, label, prefix) {
    var before = prefix || "";
    if (sourceId === "gdelt-doc-v2") {
      return esc(before) + '<a href="' + GDELT_ORIGIN +
        '" target="_blank" rel="noopener noreferrer">' + esc(label) + "</a>";
    }
    return esc(before + label);
  }

  function exactKeys(value, keys) {
    if (!value || Object.prototype.toString.call(value) !== "[object Object]") {
      return false;
    }
    var actual = Object.keys(value).sort();
    var expected = keys.slice().sort();
    return actual.length === expected.length && actual.every(function (key, index) {
      return key === expected[index];
    });
  }

  function boundedText(value, maximum, allowEmpty) {
    return typeof value === "string" && value.length <= maximum && (allowEmpty || value.length > 0);
  }

  function validInstant(value) {
    if (typeof value !== "string" ||
        !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(value)) {
      return false;
    }
    var parsed = new Date(value);
    return !isNaN(parsed.getTime()) && parsed.toISOString() === value.replace(/Z$/, ".000Z");
  }

  function validDay(value) {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
      return false;
    }
    var parts = value.split("-").map(Number);
    var parsed = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
    return parsed.getUTCFullYear() === parts[0] &&
      parsed.getUTCMonth() === parts[1] - 1 && parsed.getUTCDate() === parts[2];
  }

  function validPublished(value) {
    if (validDay(value)) { return true; }
    if (typeof value !== "string") { return false; }
    var match = value.match(
      /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?Z$/
    );
    if (!match) { return false; }
    var parts = match.slice(1).map(Number);
    var parsed = new Date(Date.UTC(
      parts[0], parts[1] - 1, parts[2], parts[3], parts[4], parts[5]
    ));
    return parsed.getUTCFullYear() === parts[0] && parsed.getUTCMonth() === parts[1] - 1 &&
      parsed.getUTCDate() === parts[2] && parsed.getUTCHours() === parts[3] &&
      parsed.getUTCMinutes() === parts[4] && parsed.getUTCSeconds() === parts[5];
  }

  function validateResearch(document) {
    if (!exactKeys(document, ["research", "schema_version", "source_dataset_version", "source_revision"]) ||
        document.schema_version !== 1 || !Array.isArray(document.research) ||
        document.research.length < 1 || document.research.length > 2000 ||
        !/^[0-9a-f]{64}$/.test(document.source_dataset_version) ||
        !/^[0-9a-f]{40}$/.test(document.source_revision)) {
      throw new Error("research payload contract failed");
    }
    document.research.forEach(function (record) {
      var keys = Object.keys(record);
      var required = ["access", "entities", "id", "published", "source", "title", "topic", "url"];
      if (!required.every(function (key) {
        return Object.prototype.hasOwnProperty.call(record, key);
      }) || !keys.every(function (key) {
        return ["access", "entities", "id", "published", "source", "summary", "title", "topic", "url"]
          .indexOf(key) !== -1 && !FORBIDDEN_KEYS[key];
      }) || !/^r_[0-9a-f]{64}$/.test(record.id) || !boundedText(record.title, 500, false) ||
          !boundedText(record.url, 2048, false) || !boundedText(record.source, 40, false) ||
          !validPublished(record.published) || !boundedText(record.topic, 80, false) ||
          !Array.isArray(record.entities) ||
          record.entities.length > 50 || ["public", "restricted", "unknown"].indexOf(record.access) === -1) {
        throw new Error("research record contract failed");
      }
      if (record.summary != null && !boundedText(record.summary, 240, true)) {
        throw new Error("research summary contract failed");
      }
    });
    return document;
  }

  function validateCompanies(document) {
    if (!exactKeys(document, ["checked_at", "companies", "fields", "schema_version", "source_id"]) ||
        document.schema_version !== 1 || document.source_id !== "sec-edgar" ||
        !validInstant(document.checked_at) ||
        JSON.stringify(document.fields) !== JSON.stringify(["cik", "ticker", "exchange", "name"]) ||
        !Array.isArray(document.companies) || document.companies.length < 1 ||
        document.companies.length > 15000) {
      throw new Error("company payload contract failed");
    }
    document.companies.forEach(function (row) {
      if (!Array.isArray(row) || row.length !== 4 ||
          !/^\d{10}$/.test(row[0]) || !boundedText(row[1], 20, false) ||
          !boundedText(row[2], 40, true) || !boundedText(row[3], 300, false)) {
        throw new Error("company row contract failed");
      }
    });
    return document;
  }

  function validateNews(document) {
    if (!exactKeys(document, ["items", "schema_version", "sources"]) ||
        document.schema_version !== 3 || !Array.isArray(document.items) ||
        document.items.length > 300 || !document.sources ||
        Object.prototype.toString.call(document.sources) !== "[object Object]") {
      throw new Error("market news payload contract failed");
    }
    document.items.forEach(function (record) {
      if (!exactKeys(record, ["attribution", "entities", "id", "published", "publisher",
                              "source_id", "title", "topic", "url"]) ||
          !boundedText(record.id, 66, false) || !boundedText(record.title, 300, false) ||
          !boundedText(record.url, 2048, false) || !boundedText(record.publisher, 253, false) ||
          !validInstant(record.published) || !Array.isArray(record.entities) ||
          record.entities.length > 50 || PROHIBITED_HEADLINE.test(record.title)) {
        throw new Error("market news record contract failed");
      }
    });
    Object.keys(document.sources).forEach(function (sourceId) {
      var source = document.sources[sourceId];
      if (!exactKeys(source, ["attribution", "item_count", "label", "last_attempt_at",
                              "last_success_at", "status"]) ||
          ["error", "never", "ok", "partial"].indexOf(source.status) === -1 ||
          typeof source.item_count !== "number" || source.item_count < 0 ||
          (source.last_attempt_at != null && !validInstant(source.last_attempt_at)) ||
          (source.last_success_at != null && !validInstant(source.last_success_at))) {
        throw new Error("market news source-state contract failed");
      }
    });
    return document;
  }

  function validateTaxonomy(document) {
    if (!exactKeys(document, ["entities", "schema_version", "sources", "topics"]) ||
        document.schema_version !== 1 || !document.entities || !document.sources || !document.topics) {
      throw new Error("taxonomy payload contract failed");
    }
    Object.keys(document.entities).forEach(function (id) {
      var entity = document.entities[id];
      if (!exactKeys(entity, ["aliases", "kind", "label"]) ||
          !boundedText(entity.label, 200, false) || !boundedText(entity.kind, 40, false) ||
          !Array.isArray(entity.aliases) || entity.aliases.length > 40) {
        throw new Error("taxonomy entity contract failed");
      }
    });
    return document;
  }

  function bytesToHex(bytes) {
    return Array.prototype.map.call(new Uint8Array(bytes), function (value) {
      return value.toString(16).padStart(2, "0");
    }).join("");
  }

  function loadJson(logical, rawUrl, validator) {
    var url = new URL(rawUrl, window.location.href);
    var filename = url.pathname.split("/").pop() || "";
    var digestMatch = filename.match(new RegExp("^" + logical + "-([0-9a-f]{16})\\.json$"));
    if (url.origin !== window.location.origin || url.search || url.hash || !digestMatch) {
      return Promise.reject(new Error(logical + " asset URL is not same-origin and content-addressed"));
    }
    return fetch(url.href, { credentials: "omit", redirect: "error" }).then(function (response) {
      var contentType = (response.headers.get("content-type") || "").toLowerCase();
      var declared = Number(response.headers.get("content-length") || 0);
      if (!response.ok || response.redirected || response.url !== url.href ||
          contentType.indexOf("application/json") !== 0 ||
          (declared && declared > DATA_CAPS[logical])) {
        throw new Error(logical + " response failed its transport contract");
      }
      return response.arrayBuffer();
    }).then(function (payload) {
      if (payload.byteLength > DATA_CAPS[logical]) {
        throw new Error(logical + " exceeds its byte ceiling");
      }
      if (!window.crypto || !window.crypto.subtle) {
        throw new Error("Web Crypto is required to verify this release");
      }
      return window.crypto.subtle.digest("SHA-256", payload).then(function (digest) {
        if (bytesToHex(digest).slice(0, 16) !== digestMatch[1]) {
          throw new Error(logical + " digest does not match its filename");
        }
        var text;
        try {
          text = new TextDecoder("utf-8", { fatal: true }).decode(payload);
          return validator(JSON.parse(text));
        } catch (error) {
          throw new Error(logical + " is not valid strict-shape JSON");
        }
      });
    });
  }

  function normalize(value) {
    return String(value || "").toLowerCase().replace(/[^a-z0-9&.+$-]+/g, " ").trim();
  }

  function tokens(value) {
    return normalize(value).split(/\s+/).filter(function (token) { return token.length > 0; });
  }

  function coreCompanyName(value) {
    return normalize(value)
      .replace(/\b(incorporated|corporation|company|limited|holdings|holding|plc|inc|corp|co|ltd|llc)\b/g, " ")
      .replace(/\s+/g, " ").trim();
  }

  function prepareRecord(record) {
    var surfaces = [];
    (record.entities || []).forEach(function (id) {
      var entity = data.entities[id];
      if (entity) { surfaces = surfaces.concat([entity.label], entity.aliases || []); }
    });
    record._entitySurfaces = surfaces;
    record._topicLabel = data.topics[record.topic] || record.topic;
    record._sourceLabel = data.sources[record.source || record.source_id] ||
      record.source || record.source_id;
    record._title = normalize(record.title);
    record._hay = normalize([
      record.title, record.summary, record.publisher, record.attribution,
      record._topicLabel, record._sourceLabel, surfaces.join(" ")
    ].join(" "));
    return record;
  }

  function install(payloads) {
    var research = payloads[0];
    var companies = payloads[1];
    var news = payloads[2];
    var taxonomy = payloads[3];
    data.entities = taxonomy.entities;
    data.topics = taxonomy.topics;
    data.sources = taxonomy.sources;
    data.newsStates = news.sources;
    data.entityLookup = {};
    Object.keys(data.entities).sort().forEach(function (id) {
      var entity = data.entities[id];
      [entity.label].concat(entity.aliases || []).forEach(function (surface) {
        var key = normalize(surface);
        if (!key) { return; }
        if (Object.prototype.hasOwnProperty.call(data.entityLookup, key) &&
            data.entityLookup[key] !== id) {
          data.entityLookup[key] = null;
        } else {
          data.entityLookup[key] = id;
        }
      });
    });
    data.research = research.research.map(prepareRecord);
    data.news = news.items.map(prepareRecord);
    data.companies = companies.companies.map(function (row, index) {
      return {
        cik: row[0], ticker: row[1], exchange: row[2], name: row[3], index: index,
        _core: coreCompanyName(row[3]),
        _hay: normalize(row[1] + " " + row[3] + " " + row[2])
      };
    });
    data.ready = true;
  }

  function formatDate(value, includeTime) {
    var text = String(value || "");
    var datePart = text.slice(0, 10).split("-");
    if (datePart.length !== 3) { return "Unknown date"; }
    var names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    var result = String(parseInt(datePart[2], 10)) + " " +
      (names[parseInt(datePart[1], 10) - 1] || "") + " " + datePart[0];
    return includeTime && text.length >= 16 ? result + " · " + text.slice(11, 16) + " UTC" : result;
  }

  function highlight(value, queryTokens) {
    var safe = esc(value);
    var pattern = queryTokens.filter(function (token) { return token.length > 1; })
      .map(function (token) { return token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); })
      .join("|");
    return pattern ? safe.replace(new RegExp("(" + pattern + ")", "gi"), "<mark>$1</mark>") : safe;
  }

  function parseQuery() {
    var raw = state.query.trim();
    var explicit = raw.match(/^\$([A-Za-z0-9.-]{1,20})$/) ||
      raw.match(/^ticker\s*:\s*([A-Za-z0-9.-]{1,20})$/i);
    var entityId = data.entityLookup[normalize(raw)] || null;
    var company = state.company;
    if (explicit) {
      var ticker = explicit[1].toUpperCase();
      company = data.companies.find(function (item) { return item.ticker === ticker; }) || null;
    }
    return { raw: raw, tokens: tokens(raw), entityId: entityId, company: company, explicit: !!explicit };
  }

  function score(record, queryTokens) {
    var total = 0;
    for (var index = 0; index < queryTokens.length; index += 1) {
      var token = queryTokens[index];
      if (record._hay.indexOf(token) === -1) { return 0; }
      if (record._title === token) { total += 40; }
      else if (record._title.indexOf(token) === 0) { total += 22; }
      else if (record._title.indexOf(token) !== -1) { total += 12; }
      if (record._entitySurfaces.some(function (surface) { return normalize(surface) === token; })) {
        total += 28;
      }
      if (normalize(record._topicLabel).indexOf(token) !== -1) { total += 6; }
    }
    return total;
  }

  function companyTerms(company) {
    if (!company) { return []; }
    var terms = [normalize(company.ticker), company._core].filter(Boolean);
    return terms.filter(function (term, index) { return terms.indexOf(term) === index; });
  }

  function selectRecords(records, query, kind, orderingOverride) {
    var result = [];
    var effectiveTokens = query.tokens;
    var companySearch = companyTerms(query.company);
    for (var index = 0; index < records.length; index += 1) {
      var record = records[index];
      if (state.topic && record.topic !== state.topic) { continue; }
      if (kind === "research" && state.access && record.access !== state.access) { continue; }
      if (query.entityId && record.entities.indexOf(query.entityId) === -1) { continue; }
      if (query.company && !companySearch.some(function (term) {
        return term.length > 1 && record._hay.indexOf(term) !== -1;
      })) { continue; }
      var relevance = 0;
      if (effectiveTokens.length && !query.company) {
        relevance = score(record, effectiveTokens);
        if (!relevance) { continue; }
      } else if (query.company) {
        relevance = companySearch.reduce(function (value, term) {
          return value + (record._title.indexOf(term) !== -1 ? 20 : record._hay.indexOf(term) !== -1 ? 5 : 0);
        }, 0);
      }
      record._score = relevance;
      result.push(record);
    }
    var ordering = orderingOverride || state.sort;
    if (ordering === "best" && !query.raw) { ordering = "newest"; }
    result.sort(function (left, right) {
      if (ordering === "best" && right._score !== left._score) { return right._score - left._score; }
      if (left.published !== right.published) {
        return ordering === "oldest"
          ? (left.published < right.published ? -1 : 1)
          : (left.published > right.published ? -1 : 1);
      }
      return left.id < right.id ? -1 : left.id > right.id ? 1 : 0;
    });
    return result;
  }

  function matchingCompanies(query) {
    if (!query.raw || query.raw.length < 2) { return []; }
    var needle = normalize(query.raw.replace(/^\$|^ticker\s*:\s*/i, ""));
    var matches = data.companies.filter(function (company) {
      return query.explicit ? normalize(company.ticker) === needle : company._hay.indexOf(needle) !== -1;
    });
    matches.sort(function (left, right) {
      function rank(company) {
        if (normalize(company.ticker) === needle) { return 0; }
        if (normalize(company.name) === needle) { return 1; }
        if (normalize(company.name).indexOf(needle) === 0) { return 2; }
        return 3;
      }
      var delta = rank(left) - rank(right);
      return delta || (left.ticker < right.ticker ? -1 : left.ticker > right.ticker ? 1 :
        left.cik < right.cik ? -1 : 1);
    });
    return matches;
  }

  function selectTopic(topicId) {
    if (!Object.prototype.hasOwnProperty.call(data.topics, topicId)) { return false; }
    if (state.view === "search") {
      state.query = data.topics[topicId];
      state.company = null;
    } else {
      state.topic = topicId;
    }
    state.limit = PAGE_SIZE;
    return true;
  }

  function entityButtons(record) {
    return (record.entities || []).slice(0, 3).map(function (id) {
      var entity = data.entities[id];
      return entity ? '<button type="button" class="tag-button" data-entity="' + esc(id) + '">' +
        esc(entity.label) + "</button>" : "";
    }).filter(Boolean);
  }

  function researchRow(record, queryTokens, level) {
    var tags = entityButtons(record);
    var metadata = [
      '<time datetime="' + esc(record.published) + '">' + esc(formatDate(record.published, false)) + "</time>",
      '<button type="button" class="tag-button dot" data-topic="' + esc(record.topic) + '">' +
        esc(record._topicLabel) + "</button>",
      '<span class="dot">' + esc(record._sourceLabel) + "</span>"
    ].concat(tags.map(function (tag) { return '<span class="dot">' + tag + "</span>"; }));
    return '<li class="row"><div class="row__top"><h' + level + '><a href="' + esc(record.url) +
      '" target="_blank" rel="noopener noreferrer">' + highlight(record.title, queryTokens) +
      "</a></h" + level + '><span class="badge badge--' + esc(record.access) + '">' +
      esc(record.access) + "</span></div>" +
      (record.summary ? '<p class="row__summary">' + highlight(record.summary, queryTokens) + "</p>" : "") +
      '<div class="row__meta">' + metadata.join("") + "</div></li>";
  }

  function newsRow(record, queryTokens, level) {
    var tags = entityButtons(record);
    var metadata = [
      '<time datetime="' + esc(record.published) + '">' + esc(formatDate(record.published, true)) + "</time>",
      '<span class="dot publisher">Publisher: ' + esc(record.publisher) + "</span>",
      '<span class="dot">' + discoveryAttribution(
        record.source_id, record.attribution, "Discovery source: "
      ) + "</span>",
      '<button type="button" class="tag-button dot" data-topic="' + esc(record.topic) + '">' +
        esc(record._topicLabel) + "</button>"
    ].concat(tags.map(function (tag) { return '<span class="dot">' + tag + "</span>"; }));
    return '<li class="row"><div class="row__top"><h' + level + '><a href="' + esc(record.url) +
      '" target="_blank" rel="noopener noreferrer">' + highlight(record.title, queryTokens) +
      "</a></h" + level + '></div><div class="row__meta">' + metadata.join("") + "</div></li>";
  }

  function companyRows(companies, level) {
    return '<ul class="companies">' + companies.map(function (company) {
      var secUrl = "https://www.sec.gov/edgar/browse/?CIK=" + encodeURIComponent(company.cik);
      return '<li class="company-row"><div><h' + level + '><span class="ticker">' +
        esc(company.ticker) + "</span>" + esc(company.name) + "</h" + level +
        '><div class="company-meta"><span>' + esc(company.exchange || "Exchange not listed") +
        '</span><span class="dot">CIK ' + esc(company.cik) + '</span><a class="dot" href="' +
        esc(secUrl) + '" target="_blank" rel="noopener noreferrer">SEC record</a></div></div>' +
        '<button type="button" class="company-select" data-company="' + company.index +
        '">Search this company</button></li>';
    }).join("") + "</ul>";
  }

  function group(title, kicker, count, body) {
    return '<section class="group"><div class="group__head"><div><div class="group__kicker">' +
      esc(kicker) + "</div><h3>" + esc(title) + "</h3></div><span>" +
      count.toLocaleString() + "</span></div>" + body + "</section>";
  }

  function renderProfile(query, research, news) {
    var entity = query.entityId ? data.entities[query.entityId] : null;
    var company = query.company;
    if (!entity && !company) {
      el.profile.hidden = true;
      el.profile.innerHTML = "";
      return;
    }
    var title = entity ? entity.label : company.name;
    var kind = entity ? entity.kind : "SEC company / ticker";
    var detail = company
      ? company.ticker + (company.exchange ? " · " + company.exchange : "") + " · CIK " + company.cik
      : "Resolved from the reviewed entity and alias table.";
    el.profile.hidden = false;
    el.profile.innerHTML = '<div class="profile__kind">' + esc(kind) + '</div><h2 id="profile-title">' +
      esc(title) + "</h2><p>" + esc(detail) + '</p><div class="profile__stats"><span class="stat"><strong>' +
      research.length.toLocaleString() + '</strong> research</span><span class="stat"><strong>' +
      news.length.toLocaleString() + "</strong> market news</span></div>";
  }

  function renderSourceStates() {
    var ids = Object.keys(data.newsStates).sort();
    return '<div class="source-states" aria-label="Market news source status">' + ids.map(function (id) {
      var source = data.newsStates[id];
      var detail;
      if (source.status === "ok") {
        detail = "Checked " + formatDate(source.last_success_at, true) + " · " +
          source.item_count.toLocaleString() + " retained";
      } else if (source.status === "partial") {
        detail = "Partially checked " + formatDate(source.last_attempt_at, true) +
          " · last complete check " + (source.last_success_at ? formatDate(source.last_success_at, true) : "not available");
      } else if (source.status === "error") {
        detail = "Check failed " + formatDate(source.last_attempt_at, true) +
          " · last successful check " + (source.last_success_at ? formatDate(source.last_success_at, true) : "not available");
      } else {
        detail = "No completed check yet";
      }
      return '<div class="source-state source-state--' + esc(source.status) + '"><strong>' +
        discoveryAttribution(id, source.label, "") + "</strong><span>" +
        esc(detail) + "</span></div>";
    }).join("") + "</div>";
  }

  function renderSearch(query) {
    state.topic = "";
    state.access = "";
    el.topicFilter.value = "";
    el.accessFilter.value = "";
    var ordering = query.raw ? "best" : "newest";
    var research = selectRecords(data.research, query, "research", ordering);
    var news = selectRecords(data.news, query, "news", ordering);
    var companies = matchingCompanies(query);
    renderProfile(query, research, news);
    el.resultsHeading.textContent = query.raw ? "Search results" : "Explore the latest metadata";
    var html = "";
    if (query.raw) {
      html += group(
        "Companies and tickers", "SEC company/ticker associations", companies.length,
        companies.length ? companyRows(companies.slice(0, SEARCH_GROUP_SIZE), 4) :
          '<div class="empty"><p>No SEC company or ticker association matches this text.</p></div>'
      );
    }
    html += group(
      "Research", "Published metadata", research.length,
      research.length ? '<ul class="rows">' + research.slice(0, SEARCH_GROUP_SIZE).map(function (record) {
        return researchRow(record, query.tokens, 4);
      }).join("") + "</ul>" : '<div class="empty"><p>No research metadata matches this search.</p></div>'
    );
    html += group(
      "Market News", "Checked public-source metadata", news.length,
      news.length ? '<ul class="rows">' + news.slice(0, SEARCH_GROUP_SIZE).map(function (record) {
        return newsRow(record, query.tokens, 4);
      }).join("") + "</ul>" : '<div class="empty"><p>No retained checked headline matches this search.</p></div>'
    );
    el.results.innerHTML = html;
    el.resultCount.textContent = (research.length + news.length + companies.length).toLocaleString() +
      " total matches";
  }

  function dedicatedRows(records, query, kind) {
    var shown = records.slice(0, state.limit);
    var html = kind === "news" ? renderSourceStates() : "";
    if (!records.length) {
      return html + '<div class="empty"><h3>Nothing matches</h3><p>Clear a filter or try another local search.</p></div>';
    }
    html += '<ul class="rows">' + shown.map(function (record) {
      return kind === "news" ? newsRow(record, query.tokens, 3) : researchRow(record, query.tokens, 3);
    }).join("") + "</ul>";
    if (shown.length < records.length) {
      html += '<button type="button" class="more-button" id="more">Show ' +
        Math.min(PAGE_SIZE, records.length - shown.length) + " more</button>";
    }
    return html;
  }

  function renderDedicated(query, kind) {
    if (!query.raw && state.sort === "best") {
      state.sort = "newest";
      el.sortFilter.value = state.sort;
    }
    var records = selectRecords(kind === "news" ? data.news : data.research, query, kind);
    renderProfile(query, kind === "research" ? records : selectRecords(data.research, query, "research"),
      kind === "news" ? records : selectRecords(data.news, query, "news"));
    el.resultsHeading.textContent = kind === "news" ? "Market News" : "Research";
    el.results.innerHTML = dedicatedRows(records, query, kind);
    el.resultCount.textContent = records.length.toLocaleString() +
      (kind === "news" ? " checked headlines" : " research records");
  }

  function setViewCopy() {
    var copy = {
      search: ["Search", "Find research, SEC company/ticker associations, and checked market news from one local search."],
      research: ["Research", "Search the complete published research metadata index. Open the source when you need the article itself."],
      news: ["Market News", "Scan delayed, checked headline metadata. Each source reports its own last attempt and last success."]
    }[state.view];
    el.pageTitle.textContent = copy[0];
    el.viewDescription.textContent = copy[1];
    el.query.placeholder = state.view === "news"
      ? "Company, regulator, or market topic"
      : "Company, ticker, fund, regulator, or topic";
    el.views.forEach(function (button) {
      button.setAttribute("aria-pressed", String(button.dataset.view === state.view));
    });
    el.filters.hidden = state.view === "search";
    el.accessWrap.hidden = state.view === "news";
  }

  function render() {
    if (!data.ready) { return; }
    setViewCopy();
    var query = parseQuery();
    if (state.view === "search") { renderSearch(query); }
    else { renderDedicated(query, state.view === "news" ? "news" : "research"); }
    el.clear.hidden = !state.query;
  }

  function fillSelect(node, entries) {
    node.innerHTML = entries.map(function (entry) {
      return '<option value="' + esc(entry[0]) + '">' + esc(entry[1]) + "</option>";
    }).join("");
  }

  function configureFilters() {
    var topicEntries = [["", "All topics"]].concat(Object.keys(data.topics).map(function (id) {
      return [id, data.topics[id]];
    }).sort(function (left, right) {
      return left[1] < right[1] ? -1 : left[1] > right[1] ? 1 : 0;
    }));
    fillSelect(el.topicFilter, topicEntries);
    fillSelect(el.accessFilter, [["", "All access"], ["public", "Public"],
      ["restricted", "Restricted"], ["unknown", "Unknown"]]);
    fillSelect(el.sortFilter, [["best", "Best match"], ["newest", "Newest"], ["oldest", "Oldest"]]);
    el.sortFilter.value = state.sort;
  }

  function debounce(fn, wait) {
    var timer = null;
    return function () {
      var args = arguments;
      clearTimeout(timer);
      timer = setTimeout(function () { fn.apply(null, args); }, wait);
    };
  }

  function announceAndFocus() {
    el.resultsHeading.focus();
  }

  function clearQuery() {
    state.query = "";
    state.company = null;
    state.limit = PAGE_SIZE;
    el.query.value = "";
    render();
  }

  function bind() {
    if (bound) { return; }
    bound = true;
    el.query.addEventListener("input", debounce(function () {
      state.query = el.query.value;
      state.company = null;
      state.limit = PAGE_SIZE;
      render();
    }, 80));
    el.clear.addEventListener("click", function () { clearQuery(); el.query.focus(); });
    el.views.forEach(function (button) {
      button.addEventListener("click", function () {
        if (!data.ready) { return; }
        state.view = button.dataset.view;
        state.limit = PAGE_SIZE;
        render();
      });
    });
    el.topicFilter.addEventListener("change", function () {
      state.topic = el.topicFilter.value; state.limit = PAGE_SIZE; render(); announceAndFocus();
    });
    el.accessFilter.addEventListener("change", function () {
      state.access = el.accessFilter.value; state.limit = PAGE_SIZE; render(); announceAndFocus();
    });
    el.sortFilter.addEventListener("change", function () {
      state.sort = el.sortFilter.value; state.limit = PAGE_SIZE; render(); announceAndFocus();
    });
    el.results.addEventListener("click", function (event) {
      var more = event.target.closest("#more");
      if (more) { state.limit += PAGE_SIZE; render(); more = document.getElementById("more"); if (more) { more.focus(); } return; }
      var companyButton = event.target.closest("[data-company]");
      if (companyButton) {
        state.company = data.companies[Number(companyButton.dataset.company)] || null;
        if (state.company) { state.query = state.company.name; el.query.value = state.query; }
        state.limit = PAGE_SIZE; render(); announceAndFocus(); return;
      }
      var entityButton = event.target.closest("[data-entity]");
      if (entityButton && data.entities[entityButton.dataset.entity]) {
        state.query = data.entities[entityButton.dataset.entity].label;
        state.company = null;
        el.query.value = state.query;
        state.limit = PAGE_SIZE; render(); announceAndFocus(); return;
      }
      var topicButton = event.target.closest("[data-topic]");
      if (topicButton && selectTopic(topicButton.dataset.topic)) {
        if (state.view === "search") {
          el.query.value = state.query;
        } else {
          el.topicFilter.value = state.topic;
        }
        render(); announceAndFocus();
      }
    });
    document.addEventListener("keydown", function (event) {
      var target = event.target;
      var editable = target && (/^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName) || target.isContentEditable);
      if (event.key === "/" && !editable) { event.preventDefault(); el.query.focus(); }
      if (event.key === "Escape" && document.activeElement === el.query && state.query) {
        event.preventDefault(); clearQuery();
      }
    });
  }

  function cacheElements() {
    el.pageTitle = document.getElementById("page-title");
    el.viewDescription = document.getElementById("view-description");
    el.query = document.getElementById("query");
    el.clear = document.getElementById("clear");
    el.filters = document.getElementById("filters");
    el.topicFilter = document.getElementById("topic-filter");
    el.accessFilter = document.getElementById("access-filter");
    el.accessWrap = document.getElementById("access-wrap");
    el.sortFilter = document.getElementById("sort-filter");
    el.resultCount = document.getElementById("result-count");
    el.loadStatus = document.getElementById("load-status");
    el.profile = document.getElementById("profile");
    el.resultsHeading = document.getElementById("results-heading");
    el.results = document.getElementById("results");
    el.views = Array.prototype.slice.call(document.querySelectorAll(".view-button"));
  }

  function showFailure(error) {
    data.ready = false;
    el.filters.hidden = true;
    el.profile.hidden = true;
    el.loadStatus.hidden = true;
    el.resultsHeading.textContent = "Release unavailable";
    el.results.innerHTML = '<div class="notice" role="alert"><h2>This release could not be verified</h2>' +
      '<p>No partial data was installed. Check your connection and retry the exact same release.</p>' +
      '<button type="button" class="retry-button" id="retry">Retry</button></div>';
    var retry = document.getElementById("retry");
    retry.addEventListener("click", function () { load(); });
    if (window.console && console.error) { console.error(error); }
  }

  function load() {
    if (loading) { return; }
    loading = true;
    el.loadStatus.hidden = false;
    el.loadStatus.textContent = "Verifying this release…";
    el.results.innerHTML = "";
    var payloads = document.getElementById("payloads");
    Promise.all([
      loadJson("research", payloads.dataset.research, validateResearch),
      loadJson("companies", payloads.dataset.companies, validateCompanies),
      loadJson("news", payloads.dataset.news, validateNews),
      loadJson("taxonomy", payloads.dataset.taxonomy, validateTaxonomy)
    ]).then(function (documents) {
      install(documents);
      configureFilters();
      el.loadStatus.hidden = true;
      loading = false;
      render();
    }).catch(function (error) {
      loading = false;
      showFailure(error);
    });
  }

  function boot() {
    cacheElements();
    bind();
    load();
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      coreCompanyName: coreCompanyName,
      data: data,
      discoveryAttribution: discoveryAttribution,
      install: install,
      matchingCompanies: matchingCompanies,
      normalize: normalize,
      parseQuery: parseQuery,
      selectTopic: selectTopic,
      selectRecords: selectRecords,
      state: state,
      validateCompanies: validateCompanies,
      validateNews: validateNews,
      validateResearch: validateResearch,
      validateTaxonomy: validateTaxonomy
    };
    return;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
}());
