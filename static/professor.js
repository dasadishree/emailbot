(function () {
    const raw = localStorage.getItem("profDetail");
    if (!raw) return;

    let prof;
    try {
        prof = JSON.parse(raw);
    } catch {
        return;
    }

    const nameEl = document.querySelector(".prof-sidebar-name");
    if (nameEl && prof.name) nameEl.textContent = prof.name;

    const roleList = document.querySelector(".prof-sidebar-section ul");
    if (roleList) {
        roleList.replaceChildren();
        if (prof.role) {
            const roleItem = document.createElement("li");
            roleItem.textContent = prof.role;
            roleList.appendChild(roleItem);
        }
        const topics = Array.isArray(prof.topics) ? prof.topics : [];
        for (const topic of topics) {
            const topicItem = document.createElement("li");
            topicItem.textContent = topic;
            roleList.appendChild(topicItem);
        }
    }

    async function checkUrl(url) {
        try {
            const res = await fetch("/api/check-url?url=" + encodeURIComponent(url));
            const data = await res.json();
            return data.ok ? data.url : null;
        } catch {
            return null;
        }
    }

    function addLink(container, href, label, linkType) {
        const br = container.querySelector('[data-link-type="' + linkType + '"]');
        if (br) br.remove();
        const a = document.createElement("a");
        a.href = href;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.className = "prof-link";
        a.dataset.linkType = linkType;
        a.textContent = label;
        container.appendChild(a);
        if (linkType === "faculty") {
            container.appendChild(document.createElement("br"));
        }
    }

    async function refreshLinks() {
        const linksCard = document.getElementById("prof-links-card");
        const linksEl = document.getElementById("prof-links");
        if (!linksEl) return;

        const existingFaculty = linksEl.querySelector('[data-link-type="faculty"]');
        const existingScholar = linksEl.querySelector('[data-link-type="scholar"]');
        const scholarUrl =
            (existingScholar && existingScholar.href) || prof.scholar_url || "";

        if (prof.profile_url) {
            const valid = await checkUrl(prof.profile_url);
            if (valid) {
                addLink(linksEl, valid, "Faculty Profile ->", "faculty");
            } else if (existingFaculty) {
                existingFaculty.remove();
            }
        }

        if (!linksEl.querySelector('[data-link-type="scholar"]') && scholarUrl) {
            addLink(linksEl, scholarUrl, "Semantic Scholar ->", "scholar");
        }

        const hasLinks = linksEl.querySelector("a");
        if (linksCard) linksCard.style.display = hasLinks ? "" : "none";
    }

    function isApiLimitMessage(message) {
        const text = (message || "").toLowerCase();
        return (
            text.includes("rate limit") ||
            text.includes("unavailable") ||
            text.includes("could not be loaded") ||
            text.includes("could not load")
        );
    }

    function setPublicationsStatus(message) {
        const grid = document.getElementById("publications-grid");
        if (!grid || grid.querySelector(".pub-card")) return;

        let statusEl = document.getElementById("publications-status");
        if (!statusEl) {
            statusEl = document.createElement("p");
            statusEl.id = "publications-status";
            statusEl.style.gridColumn = "1 / -1";
            grid.appendChild(statusEl);
        }
        statusEl.textContent = message;
        statusEl.className = isApiLimitMessage(message) ? "api-warning" : "api-notice";
    }

    function renderPublications(papers) {
        const grid = document.getElementById("publications-grid");
        if (!grid || !Array.isArray(papers) || !papers.length) return;
        if (grid.querySelector(".pub-card")) return;

        const statusEl = document.getElementById("publications-status");
        if (statusEl) statusEl.remove();
        grid.replaceChildren();
        for (const paper of papers) {
            const card = document.createElement("div");
            card.className = "pub-card";

            const titleEl = document.createElement("div");
            titleEl.className = "pub-card-img";
            if (paper.link) {
                const link = document.createElement("a");
                link.href = paper.link;
                link.target = "_blank";
                link.rel = "noopener noreferrer";
                link.textContent = paper.title || "Untitled";
                titleEl.appendChild(link);
            } else {
                titleEl.textContent = paper.title || "Untitled";
            }

            const yearEl = document.createElement("div");
            yearEl.className = "pub-card-label";
            yearEl.textContent = paper.year || "-";

            card.appendChild(titleEl);
            card.appendChild(yearEl);
            grid.appendChild(card);
        }
    }

    if (prof.publications && prof.publications.length) {
        renderPublications(prof.publications);
    } else if (prof.publications_warning) {
        setPublicationsStatus(prof.publications_warning);
    }

    refreshLinks();
})();
