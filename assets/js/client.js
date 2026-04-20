(() => {
  "use strict";

  const form = document.querySelector("#crawlForm");
  const sourceUrl = document.querySelector("#sourceUrl");
  const maxMatches = document.querySelector("#maxMatches");
  const exportButton = document.querySelector("#exportButton");
  const buttonSpinner = document.querySelector("#buttonSpinner");
  const buttonIcon = document.querySelector("#buttonIcon");
  const clearButton = document.querySelector("#clearButton");
  const copyButton = document.querySelector("#copyButton");
  const statusBox = document.querySelector("#status");
  const preview = document.querySelector("#preview");
  const fileName = document.querySelector("#fileName");
  const fileSize = document.querySelector("#fileSize");
  const createdAt = document.querySelector("#createdAt");

  let currentOutput = "";

  function getApiPath() {
    return window.location.protocol === "file:"
      ? "http://127.0.0.1:5000/api/crawl"
      : "/api/crawl";
  }

  function selectedFormat() {
    return new FormData(form).get("format") || "json";
  }

  function normalizeUrl(value) {
    const trimmed = value.trim();
    if (!trimmed) {
      return "";
    }
    return /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
  }

  function slugify(value) {
    return value
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60) || "crawl";
  }

  function buildFileName(urlValue, format) {
    let label = "crawl";
    try {
      const parsed = new URL(urlValue);
      const hostParts = parsed.hostname.replace(/^www\./, "").split(".").filter(Boolean);
      label = hostParts.length > 1 ? hostParts.slice(0, -1).join("-") : hostParts[0] || label;
    } catch (error) {
      label = urlValue;
    }
    return `${slugify(label)}.${format === "txt" ? "txt" : "json"}`;
  }

  function formatBytes(bytes) {
    if (bytes < 1024) {
      return `${bytes} B`;
    }

    const units = ["KB", "MB", "GB"];
    let value = bytes / 1024;
    let index = 0;

    while (value >= 1024 && index < units.length - 1) {
      value /= 1024;
      index += 1;
    }

    return `${value.toFixed(value >= 10 ? 1 : 2)} ${units[index]}`;
  }

  function setLoading(isLoading) {
    exportButton.disabled = isLoading;
    clearButton.disabled = isLoading;
    sourceUrl.disabled = isLoading;
    maxMatches.disabled = isLoading;
    buttonSpinner.classList.toggle("hidden", !isLoading);
    buttonIcon.classList.toggle("hidden", isLoading);
  }

  function setStatus(message, isError = false) {
    statusBox.textContent = message;
    statusBox.classList.toggle("is-error", isError);
  }

  function setPreview(text) {
    currentOutput = text;
    preview.textContent = text || "Chưa có dữ liệu";
    preview.classList.toggle("empty", !text);
    copyButton.disabled = !text;
  }

  function downloadFile(name, content, format) {
    const type = format === "json" ? "application/json;charset=utf-8" : "text/plain;charset=utf-8";
    const blob = new Blob([content], { type });
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");

    anchor.href = objectUrl;
    anchor.download = name;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(objectUrl);

    return blob.size;
  }

  async function readError(response) {
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      const data = await response.json();
      return data.error || JSON.stringify(data);
    }
    return response.text();
  }

  async function copyText(text) {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }

    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand("copy");
    textarea.remove();
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const urlValue = normalizeUrl(sourceUrl.value);
    const format = selectedFormat();
    const apiFormat = format === "txt" ? "m3u" : "json";
    const maxValue = Math.max(1, Math.min(Number(maxMatches.value) || 80, 80));

    if (!urlValue) {
      setStatus("Nhập link nguồn", true);
      sourceUrl.focus();
      return;
    }

    const params = new URLSearchParams({
      format: apiFormat,
      link: urlValue,
      max: String(maxValue),
    });

    setLoading(true);
    setStatus("Đang crawl...");
    setPreview("");

    try {
      const response = await fetch(`${getApiPath()}?${params.toString()}`, {
        headers: {
          Accept: format === "json" ? "application/json" : "text/plain",
        },
      });

      if (!response.ok) {
        throw new Error(await readError(response));
      }

      const output = format === "json"
        ? JSON.stringify(await response.json(), null, 2)
        : await response.text();
      const name = buildFileName(urlValue, format);
      const size = downloadFile(name, output, format);

      setPreview(output);
      fileName.textContent = name;
      fileSize.textContent = formatBytes(size);
      createdAt.textContent = new Date().toLocaleString("vi-VN");
      setStatus("Đã xuất file");
    } catch (error) {
      setStatus(error.message || "Không thể crawl link này", true);
      setPreview("");
    } finally {
      setLoading(false);
    }
  });

  clearButton.addEventListener("click", () => {
    setPreview("");
    fileName.textContent = "-";
    fileSize.textContent = "-";
    createdAt.textContent = "-";
    setStatus("Sẵn sàng");
    sourceUrl.focus();
  });

  copyButton.addEventListener("click", async () => {
    if (!currentOutput) {
      return;
    }

    await copyText(currentOutput);
    setStatus("Đã sao chép");
  });
})();
