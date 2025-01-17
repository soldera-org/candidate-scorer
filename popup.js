document.getElementById("startCrawl").addEventListener("click", async () => {
  // Find the active tab
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  // Set localStorage in the tab’s context
  chrome.scripting.executeScript({
    target: { tabId: tab.id },
    function: () => localStorage.setItem("linkedinCrawlerActive", "true"),
  });
});
