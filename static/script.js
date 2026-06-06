// search by school
async function search() {
    const input = document.getElementById("school-input")
    const btn = document.getElementById("search-btn")
    const status = document.getElementById("status")
    const results = document.getElementById("results")

    const school = input.value.trim()
    if(!school) return
    btn.disabled = true
    status.textContent = "Searching " + school + "..."
    results.innerHTML = ""

    let data
    try {
        const response = await fetch("/search", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({school: school})
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

    status.textContent = "found " + data.professors.length + " professors at " + data.school

    for(const prof of data.professors) {
        const card = document.createElement("div")
        card.className = "card"
        const topics = Array.isArray(prof.topics) ? prof.topics : []
        const topicsHTML = topics.map(t => `<li>${t}</li>`).join("")
        card.innerHTML = `
            <div class="card-name">${prof.name}</div>
            <div class="card-role">${prof.role}</div>
            <ul class="card-topics">${topicsHTML}</ul>
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
document.getElementById("school-input").addEventListener("keydown", function(e) {
    if(e.key==="Enter") search()
})

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
        scholar_url: prof.scholar_url || ""
    }))
    const params = new URLSearchParams({ name: prof.name, school })
    if (prof.profile_url) params.set("profile_url", prof.profile_url)
    const url = "/professor?" + params.toString()
    window.open(url, "_blank", "noopener,noreferrer")
}