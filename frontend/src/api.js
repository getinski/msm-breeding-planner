const API = '/api'

async function jsonOrThrow(res) {
  if (!res.ok) {
    let detail = ''
    try {
      const body = await res.json()
      detail = body?.error || JSON.stringify(body)
    } catch {
      detail = await res.text()
    }
    throw new Error(`HTTP ${res.status}: ${detail || res.statusText}`)
  }
  return res.json()
}

export async function fetchIslands() {
  return jsonOrThrow(await fetch(`${API}/islands`))
}

export async function fetchBoxMonsters() {
  return jsonOrThrow(await fetch(`${API}/box-monsters`))
}

export async function fetchSettings() {
  return jsonOrThrow(await fetch(`${API}/settings`))
}

export async function saveSettings(settings) {
  return jsonOrThrow(
    await fetch(`${API}/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings),
    })
  )
}

export async function generatePlan(settings) {
  const res = await fetch(`${API}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings),
  })
  if (!res.ok) {
    let body = null
    try {
      body = await res.json()
    } catch {
      // fall through with body=null
    }
    const err = new Error(body?.message || body?.error || `HTTP ${res.status}: ${res.statusText}`)
    err.code = body?.error || null
    err.details = body?.details || null
    err.status = res.status
    throw err
  }
  const blob = await res.blob()
  const summary = {
    rows:     Number(res.headers.get('X-Plan-Rows') || 0),
    islands:  Number(res.headers.get('X-Plan-Islands-Used') || 0),
    noRecipe: Number(res.headers.get('X-Plan-No-Recipe') || 0),
  }
  return { blob, summary }
}

export function triggerDownload(blob, filename = 'breeding_plan.xlsx') {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
