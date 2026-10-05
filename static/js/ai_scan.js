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

	async function copyPrompt() {
		if (!navigator.clipboard?.writeText) {
			status.textContent = "Clipboard access is unavailable. The prompt is selected; press Ctrl+C to copy it.";
			selectPrompt();
			return;
		}

		try {
			await navigator.clipboard.writeText(prompt);
			status.textContent = "Review prompt copied to clipboard.";
		} catch {
			status.textContent = "Clipboard copy failed. The prompt is selected; press Ctrl+C to copy it.";
			selectPrompt();
		}
	}

	link.addEventListener("click", copyPrompt);
	copyButton.addEventListener("click", copyPrompt);
	fallback.addEventListener("toggle", () => {
		if (fallback.open) promptField.select();
	});
})();