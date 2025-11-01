// ==============================
// CONFIG
// ==============================
const SHEET_ID = "1qciUvjQdZxTuM-lB0i4EG8dCUEM2wkDGOpVTxqx2HF8";
const BUCKET_NAME = "informedbias-news-articles";

// Gemini API
const GEMINI_API_KEY = "ADD YOUR API KEY - HIDDEN FOR GITHUB UPLOAD";
const GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent";

// ==============================
// HELPERS
// ==============================
function getSheetData() {
  const sheet = SpreadsheetApp.openById(SHEET_ID).getSheetByName("Sheet1");
  const data = sheet.getDataRange().getValues();
  const articles = [];

  for (let i = 1; i < data.length; i++) {
    const [title, url, date, category, metaStr, blobPath] = data[i];
    if (!title) continue;

    let meta = {};
    try { meta = JSON.parse(metaStr.replace(/'/g, '"')); } catch(e) {}

    let lengthLabel = "Short";
    if (meta.chunks >= 5) lengthLabel = "Long";
    else if (meta.chunks >= 3) lengthLabel = "Medium";

    const filename = title.replace(/[\\/*?:"<>|]/g, "_").substring(0, 100);

    articles.push({
      title,
      url,
      date,
      category,
      bias: meta.bias_score ?? 0,
      length: lengthLabel,
      filename
    });
  }
  return articles;
}

function getArticles() {
  return getSheetData();
}

// ==============================
// GCS FETCH FUNCTION
// ==============================
function getFullText(category, dateStr, filename) {
  const safeFilename = filename.replace(/[\\/*?:"<>|]/g, "_").substring(0, 100);
  const url = `https://storage.googleapis.com/${BUCKET_NAME}/${category}/${dateStr}/${safeFilename}.txt`;

  try {
    const response = UrlFetchApp.fetch(url);
    return response.getContentText();
  } catch (err) {
    return `Error fetching file from GCS:\n${err}`;
  }
}

// ==============================
// GEMINI TEXT ANALYSIS
// ==============================
function analyzeWithGemini(text, userQuestion) {
  const prompt = userQuestion
    ? `Based on the following article text, please answer this question: "${userQuestion}"\n\nArticle text:\n${text}`
    : `Analyze the following article text for potential bias, subjective framing, and perspective. Be specific about what language or framing choices reveal bias:\n\n${text}`;

  const payload = {
    contents: [
      { parts: [{ text: prompt }] }
    ]
  };

  const options = {
    method: "post",
    contentType: "application/json",
    headers: { "X-goog-api-key": GEMINI_API_KEY },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };

  try {
    const response = UrlFetchApp.fetch(GEMINI_ENDPOINT, options);
    const json = JSON.parse(response.getContentText());
    return json.candidates?.[0]?.content?.parts?.[0]?.text || JSON.stringify(json);
  } catch(e) {
    return `Error contacting Gemini API:\n${e}`;
  }
}

// ==============================
// WEB ENDPOINT
// ==============================
function doGet() {
  return HtmlService.createHtmlOutputFromFile("Index")
    .setTitle("Informed Reading")
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}
