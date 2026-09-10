/* Shared "working..." feedback for the app's slow synchronous POSTs.
   These requests parse a PDF and render a page in the sandbox worker
   (and can queue behind PDF_PROCESSING_SLOTS), so the browser can sit
   for a few seconds with nothing on screen.

   Opt in per form:
     <form data-busy>            -- dims the page with a centered spinner
     <form data-busy="button">   -- puts a small spinner in the clicked button

   Manual control (used by the async image-extract path in
   select_region.html, which never submits a form):
     window.PdfxmlBusy.show() / window.PdfxmlBusy.hide()

   Loaded once from base.html. Vanilla, served from 'self' so no nonce. */
(function () {
	"use strict";

	var SHOW_DELAY = 120;   // ms -- a quick reply shouldn't flash the overlay
	var overlayEl = null;
	var overlayTimer = null;

	function overlay() {
		if (!overlayEl) {
			overlayEl = document.createElement("div");
			overlayEl.className = "busy-overlay";
			overlayEl.innerHTML =
				'<span class="spinner" role="status" aria-label="Working"></span>';
			document.body.appendChild(overlayEl);
		}
		return overlayEl;
	}

	function show() {
		var el = overlay();
		clearTimeout(overlayTimer);
		overlayTimer = setTimeout(function () {
			el.classList.add("is-visible");
		}, SHOW_DELAY);
	}

	function hide() {
		clearTimeout(overlayTimer);
		if (overlayEl) overlayEl.classList.remove("is-visible");
	}

	function busyButton(btn) {
		if (!btn || btn.dataset.busyOn) return;
		btn.dataset.busyOn = "1";
		btn.dataset.busyHtml = btn.innerHTML;
		var label = btn.dataset.busyLabel;
		if (label === undefined) label = btn.textContent.trim();
		btn.innerHTML =
			'<span class="spinner spinner--sm" aria-hidden="true"></span>' +
			(label ? "<span>" + label + "</span>" : "");
		btn.classList.add("is-busy");
		btn.style.minWidth = btn.offsetWidth + "px";  // don't let it collapse
		// disable on the next tick so this very submit still goes through
		setTimeout(function () { btn.disabled = true; }, 0);
	}

	function restoreButtons() {
		var busy = document.querySelectorAll("button[data-busy-on]");
		for (var i = 0; i < busy.length; i++) {
			var b = busy[i];
			b.disabled = false;
			b.classList.remove("is-busy");
			b.style.minWidth = "";
			if (b.dataset.busyHtml !== undefined) b.innerHTML = b.dataset.busyHtml;
			delete b.dataset.busyOn;
			delete b.dataset.busyHtml;
		}
	}

	function arm(form) {
		if (form.dataset.busyArmed) return;
		form.dataset.busyArmed = "1";
		form.addEventListener("submit", function (e) {
			if (form.dataset.busyFired) {   // guard a double submit
				e.preventDefault();
				return;
			}
			var submitter = e.submitter
				|| form.querySelector("button[type=submit]:focus, input[type=submit]:focus")
				|| form.querySelector("button[type=submit], input[type=submit]");
			if ((form.dataset.busy || "overlay") === "button") {
				busyButton(submitter);
			} else {
				if (submitter) submitter.classList.add("is-busy");
				show();
			}
			form.dataset.busyFired = "1";
		});
	}

	function init() {
		var forms = document.querySelectorAll("form[data-busy]");
		for (var i = 0; i < forms.length; i++) arm(forms[i]);
	}

	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", init);
	} else {
		init();
	}

	// Back/forward cache can restore this page mid-"busy" -- clear it so
	// the controls work again.
	window.addEventListener("pageshow", function (e) {
		if (!e.persisted) return;
		hide();
		restoreButtons();
		var forms = document.querySelectorAll("form[data-busy]");
		for (var i = 0; i < forms.length; i++) {
			delete forms[i].dataset.busyFired;
			var s = forms[i].querySelector(".is-busy");
			if (s) s.classList.remove("is-busy");
		}
	});

	window.PdfxmlBusy = { show: show, hide: hide };
})();
