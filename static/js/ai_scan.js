(() => {
	const link = document.getElementById("ai-scan-link");
	const status = document.getElementById("ai-scan-status");
	const fallback = document.getElementById("ai-scan-copy-fallback");
	const promptField = document.getElementById("ai-scan-prompt");
	const copyButton = document.getElementById("ai-scan-copy-button");
	if (!link || !status || !fallback || !promptField || !copyButton) return;

	function selectPrompt() {
		fallback.open = true;
		promptField.focus();
		promptField.select();
	}

	async function copyPrompt() {
		selectPrompt();
		let copied = false;

		try {
			await navigator.clipboard.writeText(promptField.value);
			copied = true;
		} catch {
			try {
				copied = document.execCommand("copy");
			} catch {
				copied = false;
			}
		}

		status.textContent = copied
			? "Review prompt copied to clipboard."
			: "Copy failed. The prompt is selected; press Ctrl+C to copy it.";
	}

	link.addEventListener("click", copyPrompt);
	copyButton.addEventListener("click", copyPrompt);
	fallback.addEventListener("toggle", () => {
		if (fallback.open) promptField.select();
	});
})();