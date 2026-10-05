(() => {
	const link = document.getElementById("ai-scan-link");
	const status = document.getElementById("ai-scan-status");
	if (!link || !status) return;

	link.addEventListener("click", () => {
		if (!navigator.clipboard?.writeText) {
			status.textContent = "Copilot opened, but clipboard access is unavailable.";
			return;
		}

		navigator.clipboard.writeText(link.dataset.prompt || "").then(() => {
			status.textContent = "Review prompt copied to clipboard.";
		}).catch(() => {
			status.textContent = "Copilot opened, but the prompt could not be copied.";
		});
	});
})();