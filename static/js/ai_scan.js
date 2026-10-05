(() => {
	const link = document.getElementById("ai-scan-link");
	const status = document.getElementById("ai-scan-status");
	const fallback = document.getElementById("ai-scan-copy-fallback");
	const promptField = document.getElementById("ai-scan-prompt");
	const copyButton = document.getElementById("ai-scan-copy-button");
	if (!link || !status || !fallback || !promptField || !copyButton) return;

	const prompt = link.dataset.prompt || "";
	function selectPrompt() {
		fallback.open = true;
		promptField.focus();
		promptField.select();
	}
	function copyWithLegacyApi() {
		selectPrompt();
		try {
			return document.execCommand("copy");
		} catch {
			return false;
		}
	}

	async function copyPrompt() {
		if (!navigator.clipboard?.writeText) {
			const copied = copyWithLegacyApi();
			status.textContent = copied
				? "Review prompt copied using the browser fallback."
				: `Clipboard API unavailable${window.isSecureContext ? "" : " because this page is not a secure context"}. The prompt is selected; press Ctrl+C to copy it.`;
			return;
		}

		try {
			await navigator.clipboard.writeText(prompt);
			status.textContent = "Review prompt copied to clipboard.";
		} catch {
			const copied = copyWithLegacyApi();
			status.textContent = copied
				? "Review prompt copied using the browser fallback."
				: "Clipboard copy failed. The prompt is selected; press Ctrl+C to copy it.";
		}
	}

	link.addEventListener("click", copyPrompt);
	copyButton.addEventListener("click", copyPrompt);
	fallback.addEventListener("toggle", () => {
		if (fallback.open) promptField.select();
	});
})();