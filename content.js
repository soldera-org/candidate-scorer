let isCrawling = false;
let results = [];

async function crawlAllPages() {
  try {
    // 1) Get total pages from the "Page X of Y" text
    const pageState = document.querySelector(".artdeco-pagination__page-state");
    let totalPages = 1;
    if (pageState) {
      const match = pageState.innerText.match(/Page\s+\d+\s+of\s+(\d+)/);
      if (match && match[1]) {
        totalPages = parseInt(match[1], 10);
      }
    }

    for (let pageNum = 1; pageNum <= totalPages; pageNum++) {
      if (!isCrawling) break;

      // If not on first page, click that page button
      // e.g. <li data-test-pagination-page-btn="2" ...><button ...>2</button></li>
      if (pageNum > 1) {
        const pageBtnLi = document.querySelector(
          `li[data-test-pagination-page-btn="${pageNum}"]`
        );
        if (pageBtnLi) {
          const button = pageBtnLi.querySelector("button");
          if (button) {
            button.click();
            console.log(`Clicked on page ${pageNum}... waiting to load`);
            await waitForDOM(3000);
          }
        }
      }

      // Now scrape all candidates on the current page
      await scrapeCandidatesOnPage();
    }

    // After all pages are processed, download the CSV if we have results
    if (results.length) {
      const csv = convertToCSV(results);
      downloadCSV(csv, "candidates.csv");
    }

    // Reset flags
    isCrawling = false;
    localStorage.removeItem("linkedinCrawlerActive");
  } catch (err) {
    console.error("Error in crawlAllPages:", err);
  }
}

async function scrapeCandidatesOnPage() {
  // Grab all candidate <a> tags in the left panel
  const candidateLinks = document.querySelectorAll(
    'li.hiring-applicants__list-item[data-view-name="job-applicant-list-profile-card"] a.ember-view'
  );

  for (let i = 0; i < candidateLinks.length; i++) {
    if (!isCrawling) break;

    // Click candidate to load details in right panel
    candidateLinks[i].click();
    await waitForDOM(3000);

    // Check for virus scan
    const virusCard = document.querySelector(".p0.mt4.artdeco-card");
    if (
      virusCard &&
      virusCard.innerText.includes("Scanning resume for viruses")
    ) {
      console.log("Virus scan in progress; waiting 5s, then reloading...");
      await waitForDOM(5000);
      window.location.reload();
      return; // End function so page reloads
    }

    // Identify resume filename
    let resumeFilename = "";
    const resumeLink = document.querySelector(
      'div.hiring-resume-viewer__resume-wrapper--collapsed a[aria-label^="Download"]'
    );
    if (resumeLink) {
      const pdfUrl = resumeLink.getAttribute("href");
      if (pdfUrl) {
        resumeFilename = `candidate_resume_${Date.now()}.pdf`;
        sendDownloadRequest(pdfUrl, resumeFilename);
      }
    }

    // Expand “Show more experiences” if present
    const showMoreExpBtn = document.querySelector(
      'button.artdeco-button--icon-right.artdeco-button--tertiary[aria-expanded="false"]'
    );
    if (showMoreExpBtn && showMoreExpBtn.innerText.includes("Show")) {
      showMoreExpBtn.click();
      await waitForDOM(1500);
    }

    // Gather experiences
    let experiencesText = "";
    let expItems = document.querySelectorAll(
      ".artdeco-card.mt4.p0 ul.list-style-none.mt2 li.display-flex.align-items-center.mb3"
    );
    const hiddenExpItems = document.querySelectorAll(
      ".artdeco-card.mt4.p0 ul.list-style-none.mt2 li.display-flex.align-items-center.mb3.visually-hidden"
    );
    expItems = [...expItems, ...hiddenExpItems];
    expItems.forEach((item) => {
      experiencesText += item.innerText.trim().replace(/\n+/g, " | ") + "\n";
    });

    // Gather screening responses
    let screeningResponses = "";
    const screeningListItems = document.querySelectorAll(
      ".job-posting-shared-screening-question-list__list-item"
    );
    screeningListItems.forEach((li) => {
      const question = li.querySelector("p.t-14");
      const answer = li.querySelector("p.t-14.t-bold.mt1");
      if (question && answer) {
        screeningResponses += `Q: ${question.innerText.trim()} | A: ${answer.innerText.trim()}\n`;
      }
    });

    // Applicant name (from right panel header)
    const nameHeading = document.querySelector(".hiring-applicant-header h1");
    const name = nameHeading
      ? nameHeading.innerText.replace(/’s application.*/, "").trim()
      : `Candidate ${Date.now()}`;

    results.push({
      name,
      resumeFilename,
      experiences: experiencesText.trim(),
      screening: screeningResponses.trim(),
    });
  }
}

/** Converts results to CSV text. */
function convertToCSV(data) {
  const header = "Name,ResumeFile,Experiences,Screening\n";
  const rows = data.map((item) => {
    const safeName = (item.name || "").replace(/"/g, '""');
    const safeResume = (item.resumeFilename || "").replace(/"/g, '""');
    const safeExp = (item.experiences || "")
      .replace(/"/g, '""')
      .replace(/\n/g, " | ");
    const safeScreen = (item.screening || "")
      .replace(/"/g, '""')
      .replace(/\n/g, " | ");
    return `"${safeName}","${safeResume}","${safeExp}","${safeScreen}"`;
  });
  return header + rows.join("\n");
}

/** Utility to wait for a given time. */
function waitForDOM(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Sends a download request (to background.js) */
function sendDownloadRequest(url, filename) {
  chrome.runtime.sendMessage({ downloadUrl: url, filename });
}

/** Creates a blob from CSV text and triggers a download. */
function downloadCSV(csvContent, filename) {
  const blob = new Blob([csvContent], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  sendDownloadRequest(url, filename);
}

/** Periodically checks if we should start crawling. */
setInterval(() => {
  const activeFlag = localStorage.getItem("linkedinCrawlerActive") === "true";
  if (activeFlag && !isCrawling) {
    isCrawling = true;
    crawlAllPages();
  }
}, 2000);
