function clearWarnings() {
    const warnEl = document.getElementById("status-warnings")
    if (warnEl) warnEl.replaceChildren()
}

function showWarnings(warnings) {
    const warnEl = document.getElementById("status-warnings")
    if (!warnEl || !warnings || !warnings.length) return
    clearWarnings()
    for (const warning of warnings) {
        const p = document.createElement("p")
        p.className = "api-warning"
        p.textContent = warning
        warnEl.appendChild(p)
    }
}

// search by school and research category
async function search() {
    const schoolInput = document.getElementById("school-input")
    const categoryInput = document.getElementById("category-input")
    const btn = document.getElementById("search-btn")
    const status = document.getElementById("status")
    const results = document.getElementById("results")

    const school = schoolInput.value.trim()
    const category = categoryInput.value.trim()
    // makew sure they entered smth
    if (!school) {
        status.textContent = "Please enter a university."
        return
    }
    if (!category) {
        status.textContent = "Please enter at least one research area."
        return
    }
    btn.disabled = true
    status.textContent = "Searching " + school + " for " + category + "..."
    clearWarnings()
    results.innerHTML = ""

    let data
    // ai debug search
    try {
        const response = await fetch("/search", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ school, category })
        })
        data = await response.json()
        if (!response.ok) {
            status.textContent = data.error || "Search failed. Please try again."
            btn.disabled = false
            return
        }
    } catch (err) {
        status.textContent = "Search failed. Is the server running?"
        btn.disabled = false
        return
    }

    if (!Array.isArray(data.professors)) {
        status.textContent = "Unexpected response from server."
        btn.disabled = false
        return
    }

    if (data.professors.length === 0) {
        status.textContent = data.message || "No professors found. Try broader research areas or a different university."
        btn.disabled = false
        return
    }

    status.textContent =
        "found " + data.professors.length + " professors at " + data.school +
        (data.category ? " in " + data.category : "")
    showWarnings(data.warnings)

    for(const prof of data.professors) {
        const card = document.createElement("div")
        card.className = "card"
        const topics = Array.isArray(prof.topics) ? prof.topics : []
        const topicsHTML = topics.map(t => `<li>${t}</li>`).join("")
        const matchNote = prof.matched_areas && prof.matched_areas.length
            ? `<div class="card-match">matches: ${prof.matched_areas.join(", ")}</div>`
            : ""
        card.innerHTML = `
            <div class="card-name">${prof.name}</div>
            <div class="card-role">${prof.role}</div>
            <ul class="card-topics">${topicsHTML}</ul>
            ${matchNote}
            `
        const btn = document.createElement("button")
        btn.className = "card-btn"
        btn.textContent = "see publications and more info"
        btn.addEventListener("click", () => openProf(prof, data.school))
        card.appendChild(btn)
        results.appendChild(card)
    }
    btn.disabled = false
}
function onSearchKeydown(e) {
    if (e.key === "Enter") search()
}
document.getElementById("school-input").addEventListener("keydown", onSearchKeydown)
document.getElementById("category-input").addEventListener("keydown", onSearchKeydown)

// open details (see publciations button)
function openProf(prof, school) {
    localStorage.setItem("profDetail", JSON.stringify({
        name: prof.name,
        school,
        role: prof.role,
        department: prof.department,
        topics: prof.topics,
        summary: prof.research_summary,
        email: prof.email || "",
        profile_url: prof.profile_url || "",
        scholar_url: prof.scholar_url || "",
        publications: prof.publications || [],
        publications_warning: prof.publications_warning || ""
    }))
    const params = new URLSearchParams({ name: prof.name, school })
    if (prof.profile_url) params.set("profile_url", prof.profile_url)
    const url = "/professor?" + params.toString()
    window.open(url, "_blank", "noopener,noreferrer")
}