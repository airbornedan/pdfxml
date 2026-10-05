(() => {
	const link = document.getElementById("ai-scan-link");
	const status = document.getElementById("ai-scan-status");
	const promptField = document.getElementById("ai-scan-prompt");
	if (!link || !status || !promptField) return;

	function selectPrompt() {
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
			: "Could not copy the review prompt to the clipboard.";
	}

	link.addEventListener("click", copyPrompt);
})();