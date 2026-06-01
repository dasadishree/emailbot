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

    const response = await fetch("/search", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({school: school})
    })
    const data = await response.json()
    status.textContent = "found " + data.professors.length + " professors at " + data.school

    for(const prof of data.professors) {
        const card = document.createElement("div")
        card.className = "card"
        const topicsHTML = prof.topics.map(t => `<li>${t}</li>`).join("")
        card.innerHTML = `
            <div class="card-name">${prof.name}</div>
            <div class="card-role">${prof.role}</div>
            <ul class="card-topics">${topicsHTML}</ul>
            <button class="card-btn" onclick="openProf('${encodeURIComponent(prof.name)}', '${encodeURIComponent(data.school)}', '${encodeURIComponent(prof.role)}', '${encodeURIComponent(prof.department)}', '${encodeURIComponent(JSON.stringify(prof.topics))}, '${encodeURIComponent(prof.research_summary)}', '${encodeURIComponent(prof.email || "")}', '${encodeURIComponent(prof.profile_url || "")}')">see publications and more info</button>
        `
        results.appendChild(card)
    }
    btn.disabled = false
}
document.getElementById("school-input").addEventListener("keydown", function(e) {
    if(e.key==="Enter") search()
})

function openProf(name, school, role, department, topics, summary, email, profileUrl){
    const params = new URLSearchParams({
        name, school, role, department, topics, summary, email, profileUrl
    })
    window.location.href = "/professor?" + params.toString()
}