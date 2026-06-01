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
    status.textContent = "Found " + data.professors.length + " professors at " + data.school

    for(const prof of data.professors) {
        const card = document.createElement("div")
        card.className = "card"
        card.innerHTML = `
            <div>${prof.name}</div>
            <div>${prof.role}</div>
            <div>${prof.topics.map(t=>`<span class="tag">${t}</span>`).join("")}</div>
        `
        results.appendChild(card)
    }
    btn.disabled = false
}
document.getElementById("school-input").addEventListener("keydown", function(e) {
    if(e.key==="Enter") search()
})