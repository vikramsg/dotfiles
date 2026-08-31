(() => {
  "use strict";

  const configuration = window.macflow.configuration;
  const sourcesElement = document.querySelector("#sources");
  const filesElement = document.querySelector("#files");
  let selectedSource = configuration.sources[0];
  let loadSequence = 0;
  let renderedSignature = "";
  let loading = false;
  let reloadRequested = false;

  document.documentElement.style.setProperty("--thumbnail-width", `${configuration.thumbnail_width}px`);
  document.documentElement.style.setProperty("--shelf-spacing", `${configuration.spacing}px`);
  document.documentElement.style.setProperty("--shelf-margin", `${configuration.margin}px`);

  const icons = {
    desktop: '<svg viewBox="0 0 18 18" aria-hidden="true"><rect x="2" y="3" width="14" height="10" rx="1.5"></rect><path d="M6 16h6M9 13v3"></path></svg>',
    network: '<svg viewBox="0 0 18 18" aria-hidden="true"><circle cx="9" cy="9" r="6.5"></circle><path d="M2.5 9h13M9 2.5c2 2 3 4.2 3 6.5s-1 4.5-3 6.5M9 2.5C7 4.5 6 6.7 6 9s1 4.5 3 6.5"></path></svg>'
  };

  function renderSources() {
    sourcesElement.replaceChildren();
    if (configuration.sources.length < 2) {
      sourcesElement.hidden = true;
      document.querySelector("#shelf").style.gridTemplateRows = "minmax(0, 1fr)";
      return;
    }
    for (const source of configuration.sources) {
      const button = document.createElement("button");
      button.className = "source";
      button.type = "button";
      button.setAttribute("aria-selected", String(source.id === selectedSource.id));
      button.innerHTML = `${icons[source.icon] || ""}<span></span>`;
      button.querySelector("span").textContent = source.label;
      button.addEventListener("click", () => {
        if (source.id === selectedSource.id) return;
        selectedSource = source;
        renderedSignature = "";
        renderSources();
        loadFiles();
      });
      sourcesElement.append(button);
    }
  }

  function showMessage(message) {
    const element = document.createElement("div");
    element.className = "message";
    element.textContent = message;
    filesElement.replaceChildren(element);
  }

  function renderFiles(files) {
    const signature = files.map(file => `${file.path}:${file.modifiedAt}`).join("|");
    if (signature === renderedSignature) return;
    renderedSignature = signature;
    if (files.length === 0) {
      showMessage("No files available");
      return;
    }

    const fragment = document.createDocumentFragment();
    for (const file of files) {
      const item = document.createElement("div");
      item.className = "thumbnail";
      item.title = file.name;
      item.tabIndex = 0;
      if (file.thumbnail) {
        const image = document.createElement("img");
        image.src = file.thumbnail;
        image.alt = "";
        item.append(image);
      }
      const label = document.createElement("span");
      label.textContent = file.name;
      item.append(label);
      item.addEventListener("pointerdown", () => {
        window.macflow.files.prepareDrag(file.path).catch(console.error);
      });
      item.addEventListener("click", () => {
        window.macflow.files.open(file.path).catch(console.error);
      });
      item.addEventListener("contextmenu", event => {
        event.preventDefault();
        window.macflow.files.reveal(file.path).catch(console.error);
      });
      item.addEventListener("keydown", event => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          window.macflow.files.open(file.path).catch(console.error);
        }
      });
      fragment.append(item);
    }
    filesElement.replaceChildren(fragment);
  }

  async function loadFiles() {
    if (loading) {
      reloadRequested = true;
      return;
    }
    loading = true;
    const sequence = ++loadSequence;
    const source = selectedSource;
    try {
      const files = await window.macflow.files.list({
        directory: source.directory,
        extensions: configuration.extensions,
        limit: configuration.max_items
      });
      if (sequence === loadSequence && source.id === selectedSource.id) renderFiles(files);
    } catch (error) {
      if (sequence === loadSequence) showMessage("Directory unavailable");
      console.error(error);
      window.macflow.diagnostics.log(String(error)).catch(console.error);
    } finally {
      loading = false;
      if (reloadRequested) {
        reloadRequested = false;
        loadFiles();
      }
    }
  }

  document.addEventListener("keydown", event => {
    if (event.key === "Escape") window.macflow.surface.dismiss().catch(console.error);
  });

  renderSources();
  loadFiles();
  window.setInterval(loadFiles, 750);
})();
