import "babel-polyfill";
import * as Sentry from "@sentry/browser";

import Tabs from "./components/tabs";
import MenuToggle from "./components/menu-toggle";
import AmountToggle from "./components/donation-amount-toggle";
import CurrencySelect from "./components/currency-selector";
import WayPointDetect from "./components/waypoint-detection";
import DonationCurrencyWidth from "./components/donation-currency-width";
import CopyURL from "./components/copy-url";
import Accordion from "./components/accordion";
import "./components/newsletter";

const doNotTrack = navigator.doNotTrack || navigator.msDoNotTrack || window.doNotTrack;
const allowGA = !doNotTrack || doNotTrack === "no" || doNotTrack === "unspecified";

function fetchEnv(callback) {
  let envReq = new XMLHttpRequest();

  envReq.addEventListener("load", () => {
    let data = {};
    try {
      data = JSON.parse(envReq.response);
    } catch (e) {
      // discard
    }
    callback(data);
  });

  envReq.open("GET", "/environment.json");
  envReq.send();
}

// Manage tab index for primary nav
function tabIndexer() {
  document.querySelectorAll("[data-nav-tab-index]").forEach(navLink => {
    navLink.tabIndex = "-1";
  });
}

// Open the mobile menu callback
function openMenu() {
  document.querySelector("[data-primary-nav]").classList.add("is-visible");
  document.querySelectorAll("[data-nav-tab-index]").forEach(navLink => {
    navLink.removeAttribute("tabindex");
  });
}

// Close the mobile menu callback
function closeMenu() {
  document.querySelector("[data-primary-nav]").classList.remove("is-visible");
  tabIndexer();
}

// Google Analytics
function initializeGA(trackingId) {
  ga("create", trackingId, "auto");

  // Ensure we don't pass the email query param to Google Analytics
  var loc = window.location,
    protocol = loc.protocol,
    hostname = loc.hostname,
    pathname = loc.pathname,
    filteredQueryParams = loc.search
      .substring(1)
      .split("&")
      .filter(param => !param.startsWith("email"))
      .join("&");

  ga(
    "set",
    "location",
    `${protocol}//${hostname}${pathname}?${filteredQueryParams}`
  );
  ga("send", "pageview");
  ga("require", "ecommerce");

  // Check for any events sent by the view, and fire them.
  var gaEventsNode = document.getElementById("ga-events");
  if (gaEventsNode) {
    var events = JSON.parse(gaEventsNode.textContent);
    events.forEach(eventArray => {
      ga(...eventArray);
    });
  }

  // Click events
  for (const a of document.querySelectorAll(".js-ga-track-click")) {
    a.addEventListener("click", e => {
      ga("send", "event", {
        eventCategory: a.getAttribute("data-ga-category"),
        eventAction: a.getAttribute("data-ga-action"),
        eventLabel: a.getAttribute("data-ga-label"),
        transport: "beacon"
      });
    });
  }
}

document.addEventListener("DOMContentLoaded", function() {
  // Initialize Sentry error reporting and analytics

  fetchEnv(envData => {
    const {
      GA_TRACKING_ID: trackingId,
      SENTRY_DSN: dsn,
      RELEASE_VERSION: release,
      SENTRY_ENVIRONMENT: environment
    } = envData;

    if (allowGA && typeof ga === "function" && trackingId) {
      initializeGA(trackingId);
    }

    if (dsn) {
      Sentry.init({ dsn, release, environment });
    }
  });

  for (const menutoggle of document.querySelectorAll(MenuToggle.selector())) {
    new MenuToggle(menutoggle, openMenu, closeMenu);
  }

  for (const currencywidth of document.querySelectorAll(
    DonationCurrencyWidth.selector()
  )) {
    new DonationCurrencyWidth(currencywidth);
  }

  for (const donatetoggle of document.querySelectorAll(
    AmountToggle.selector()
  )) {
    new AmountToggle(donatetoggle);
  }

  for (const tabs of document.querySelectorAll(Tabs.selector())) {
    new Tabs(tabs);
  }

  tabIndexer();

  for (const currencySelect of document.querySelectorAll(
    CurrencySelect.selector()
  )) {
    new CurrencySelect(currencySelect);
  }

  WayPointDetect();

  for (const accordion of document.querySelectorAll(Accordion.selector())) {
    new Accordion(accordion);
  }

  for (const copyurl of document.querySelectorAll(CopyURL.selector())) {
    new CopyURL(copyurl);
  }
});

if (allowGA) {
  // Load the GA script
  (function(i, s, o, g, r, a, m) {
    i["GoogleAnalyticsObject"] = r;
    (i[r] =
      i[r] ||
      function() {
        (i[r].q = i[r].q || []).push(arguments);
      }),
      (i[r].l = 1 * new Date());
    (a = s.createElement(o)), (m = s.getElementsByTagName(o)[0]);
    a.async = 1;
    a.src = g;
    m.parentNode.insertBefore(a, m);
  })(
    window,
    document,
    "script",
    "https://www.google-analytics.com/analytics.js",
    "ga"
  );
}
