chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.downloadUrl && request.filename) {
    chrome.downloads.download({
      url: request.downloadUrl,
      filename: request.filename,
    });
  }
});
